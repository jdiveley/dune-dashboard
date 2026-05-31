"""Chat service - chat history and log parsing"""

import base64
import json
import datetime
import logging

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, db_service, k8s_service, ssh_service, cache):
        self.db = db_service
        self.k8s = k8s_service
        self.ssh = ssh_service
        self.cache = cache
        self.ensured_table = False

    def ensure_history_table(self):
        if self.ensured_table:
            return True
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS dashboard.chat_history (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT NOW(),
                    channel VARCHAR(50),
                    sender VARCHAR(255),
                    message TEXT,
                    target VARCHAR(255),
                    location_x FLOAT,
                    location_y FLOAT,
                    location_z FLOAT,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            """)
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_timestamp ON dashboard.chat_history (timestamp DESC)")
            self.ensured_table = True
            logger.info("Chat history table ready")
            return True
        except Exception as e:
            logger.error(f"Failed to create chat history table: {e}")
            return False

    def save_message(self, channel, sender, message, target='', location=None, is_admin=False):
        loc_x = location.get('X', 0) if location else 0
        loc_y = location.get('Y', 0) if location else 0
        loc_z = location.get('Z', 0) if location else 0
        return self.db.execute("""
            INSERT INTO dashboard.chat_history (channel, sender, message, target, location_x, location_y, location_z, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, [channel, sender, message, target, loc_x, loc_y, loc_z, is_admin])

    def save_messages_batch(self, messages):
        if not messages:
            return 0
        conn = self.db.get_connection()
        if not conn:
            return 0
        cur = None
        try:
            cur = conn.cursor()
            for msg in messages:
                cur.execute("""
                    INSERT INTO dashboard.chat_history (channel, sender, message, target, location_x, location_y, location_z, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                    msg['channel'], msg['sender'], msg['message'],
                    msg.get('target', ''),
                    msg.get('location', {}).get('X', 0),
                    msg.get('location', {}).get('Y', 0),
                    msg.get('location', {}).get('Z', 0),
                    msg.get('is_admin', False)
                ])
            conn.commit()
            return len(messages)
        except Exception as e:
            logger.error(f"Failed to save chat messages batch: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn)

    def get_history(self, limit=200):
        return self.db.query("""
            SELECT id, timestamp, channel, sender, message, target,
                   location_x, location_y, location_z, is_admin
            FROM dashboard.chat_history
            ORDER BY timestamp DESC
            LIMIT %s
        """, [limit])

    def catch_up(self, namespace):
        db_messages = self.get_history(1)
        has_history = db_messages and len(db_messages) >= 10
        if has_history:
            return 0

        if not namespace:
            logger.warning("Cannot catch up - kubernetes namespace not set")
            return 0

        pod_name = self.k8s.get_text_router_pod()
        if not pod_name:
            logger.warning("Cannot catch up - no text-router pod found")
            return 0

        logger.debug(f"Attempting to catch up chat from pod: {pod_name}")

        # Get pod logs first, then filter locally
        log_cmd = f"sudo kubectl logs -n {namespace} {pod_name} --tail=2000 2>/dev/null"
        out, err, rc = self.ssh.run(log_cmd, timeout=30)

        if rc != 0 or not out:
            logger.debug(f"Cannot catch up - failed to get pod logs (rc={rc})")
            return 0

        # Filter for chat messages locally
        lines = [line for line in out.split('\n') if 'CLOG' in line and 'TextChat' in line]
        lines = [line for line in lines if 'Starting filtering' not in line]
        lines = [line for line in lines if 'Skipping filtering' not in line]
        lines = [line for line in lines if 'Redirected message' not in line]

        messages = []
        seen = set()
        for line in lines:
            if not line.strip():
                continue
            try:
                idx = line.index('received message from ')
                rest = line[idx + len('received message from '):]
                parts = rest.split(' to ', 1)
                if len(parts) < 2:
                    continue
                sender_id = parts[0].strip()
                target_and_json = parts[1]
                target_idx = target_and_json.index(': ')
                target = target_and_json[:target_idx].strip()
                msg_str = target_and_json[target_idx + 2:].strip()

                msg_data = json.loads(msg_str)
                content = json.loads(msg_data.get('content', '{}'))

                dedup_key = (
                    content.get('m_ChannelType', ''),
                    content.get('m_FuncomIdFrom', ''),
                    content.get('m_Message', {}).get('m_UnlocalizedMessage', ''),
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                messages.append({
                    'channel': content.get('m_ChannelType', 'Unknown'),
                    'sender': content.get('m_FuncomIdFrom', sender_id),
                    'message': content.get('m_Message', {}).get('m_UnlocalizedMessage', ''),
                    'target': target,
                    'location': content.get('m_OriginLocation', {}),
                    'is_admin': False,
                })
            except (ValueError, KeyError, json.JSONDecodeError, IndexError):
                continue

        if messages:
            saved = self.save_messages_batch(messages)
            logger.info(f"Caught up {saved} chat messages from pod logs")
            return saved
        return 0

    def broadcast_chat(self, message, sender_name=None, sender_funcom_id=None):
        """Inject a TextChat message to all online players via RabbitMQ rabbitmqctl eval."""
        if not sender_name or not sender_funcom_id:
            return False, "broadcast_sender_name and broadcast_sender_funcom_id must be set in settings.yaml under battlegroup"

        # Player queues/bindings live on mq-game, not mq-admin
        pod_name = self.k8s.find_pod_by_pattern('mq-game')
        if not pod_name:
            logger.warning("broadcast_chat: no mq-game pod found")
            return False, "No mq-game pod found"

        namespace = self.k8s.namespace

        # Base64 encode only the variable user inputs to avoid shell/Erlang escaping issues.
        # The JSON is built in Erlang using the same pattern as inject_fixed.erl (proven working).
        msg_b64 = base64.b64encode(message.encode('utf-8')).decode('ascii')
        name_b64 = base64.b64encode(sender_name.encode('utf-8')).decode('ascii')
        sender_id_b64 = base64.b64encode(sender_funcom_id.encode('utf-8')).decode('ascii')

        erlang_script = (
            f'Msg = base64:decode(<<"{msg_b64}">>),\n'
            f'SenderName = base64:decode(<<"{name_b64}">>),\n'
            f'SenderId = base64:decode(<<"{sender_id_b64}">>),\n'
            '{{Y,Mo,D},{H,Mi,S}} = calendar:universal_time(),\n'
            'Timestamp = iolist_to_binary(io_lib:format("~4..0B.~2..0B.~2..0B-~2..0B.~2..0B.~2..0B", [Y,Mo,D,H,Mi,S])),\n'
            'MsgId = iolist_to_binary([io_lib:format("~8.16.0B", [rand:uniform(4294967295)]) || _ <- lists:seq(1,4)]),\n'
            'UniqueId = iolist_to_binary([io_lib:format("~4.16.0B", [rand:uniform(65535)]) || _ <- lists:seq(1,4)]),\n'
            'EscQ = fun(B) -> binary:replace(B, <<"\\\"">>, <<"\\\\\\\"">>, [global]) end,\n'
            'InnerJson = iolist_to_binary([\n'
            '  <<"{">>,\n'
            '  <<"\\"m_Id\\":\\\"">>, MsgId, <<"\\\",">>,\n'
            '  <<"\\"m_ChannelType\\":\\"Map\\",">>,\n'
            '  <<"\\"m_bUseSpoofedUserName\\":false,">>,\n'
            '  <<"\\"m_SpoofedUserNameFrom\\":{\\"m_TableId\\":\\"\\",\\"m_Key\\":\\"\\",\\"m_UnlocalizedName\\":\\"\\"},">>,\n'
            '  <<"\\"m_FuncomIdFrom\\":\\\"">>, EscQ(SenderName), <<"\\\",">>,\n'
            '  <<"\\"m_UserNameTo\\":\\"\\",">>,\n'
            '  <<"\\"m_Message\\":{\\"m_UnlocalizedMessage\\":\\\"">>, EscQ(Msg), <<"\\\",\\"m_LocalizedMessage\\":{\\"m_TableId\\":\\"\\",\\"m_Key\\":\\"\\",\\"m_FormatArgs\\":[]}},">>,\n'
            '  <<"\\"m_Timestamp\\":\\\"">>, Timestamp, <<"\\\",">>,\n'
            '  <<"\\"m_OriginLocation\\":{\\"X\\":0.0,\\"Y\\":0.0,\\"Z\\":0.0},">>,\n'
            '  <<"\\"m_HasSeenMessage\\":false}">>\n'
            ']),\n'
            'InnerEsc = binary:replace(InnerJson, <<"\\\"">>, <<"\\\\\\\"">>, [global]),\n'
            'Outer = iolist_to_binary([<<"{\\\"content\\\":\\\"">>, InnerEsc, <<"\\\",\\\"Type\\\":\\\"TextChat\\\"}">>]),\n'
            'Tag = binary_to_atom(<<"P_basic">>, utf8),\n'
            'Props = {Tag, <<"Content">>, undefined,\n'
            '  [{<<"redirect_exchange">>, binary, <<"chat.map">>}],\n'
            '  undefined, undefined, undefined, undefined, undefined,\n'
            '  UniqueId, undefined, <<"text_chat">>, SenderId, undefined, undefined},\n'
            'PropsBin = rabbit_framing_amqp_0_9_1:encode_properties(Props),\n'
            'XName = rabbit_misc:r(<<"/">>, exchange, <<"chat.map">>),\n'
            'Bindings = rabbit_binding:list_for_source(XName),\n'
            'UniqueKeys = lists:usort([RKey || {binding, _, RKey, _, _} <- Bindings]),\n'
            'lists:map(fun(RKey) ->\n'
            '  Content = {content, 60, Props, PropsBin, rabbit_framing_amqp_0_9_1, [Outer]},\n'
            '  {ok, Mc} = mc_amqpl:message(XName, RKey, Content),\n'
            '  {ok, X} = rabbit_exchange:lookup(XName),\n'
            '  RouteResult = rabbit_exchange:route(X, Mc),\n'
            '  QList = rabbit_amqqueue:lookup_many(RouteResult),\n'
            '  rabbit_queue_type:deliver(QList, Mc, #{}, rabbit_queue_type:init()),\n'
            '  {sent, RKey}\n'
            'end, UniqueKeys).\n'
        )

        # Write script to game server via base64 to avoid shell quoting issues
        script_path = '/tmp/dashboard_broadcast.erl'
        script_b64 = base64.b64encode(erlang_script.encode('utf-8')).decode('ascii')
        write_cmd = f"echo '{script_b64}' | base64 -d > {script_path}"
        _, err, rc = self.ssh.run(write_cmd, timeout=10)
        if rc != 0:
            logger.error("broadcast_chat: failed to write script: %s", err)
            return False, f"Failed to write script: {err}"

        cp_cmd = f"sudo kubectl cp {script_path} {namespace}/{pod_name}:{script_path}"
        _, err, rc = self.ssh.run(cp_cmd, timeout=30)
        if rc != 0:
            logger.error("broadcast_chat: kubectl cp failed: %s", err)
            return False, f"Failed to copy script to pod: {err}"

        exec_cmd = f"sudo kubectl exec -n {namespace} {pod_name} -- rabbitmqctl eval_file {script_path}"
        out, err, rc = self.ssh.run(exec_cmd, timeout=30)
        if rc != 0:
            logger.error("broadcast_chat: eval_file failed (rc=%d): %s %s", rc, out, err)
            return False, f"RabbitMQ error: {(err or out or '')[:200]}"

        logger.info("broadcast_chat: sent '%s...' result: %s", message[:40], out.strip()[:100])
        return True, out.strip()

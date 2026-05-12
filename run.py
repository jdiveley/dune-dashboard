#!/usr/bin/env python3
"""Dune Awakening Dashboard - Entry Point"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.factory import create_app

app, socketio = create_app()

if __name__ == '__main__':
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    settings = app.dune_settings
    host = settings['dashboard']['host']
    port = settings['dashboard']['port']
    debug = settings['dashboard']['debug']

    # SSL Configuration
    ssl_context = None
    ssl_cert = settings['dashboard'].get('ssl_cert')
    ssl_key = settings['dashboard'].get('ssl_key')
    
    # Handle YAML null/None and string paths
    if ssl_cert and ssl_key and ssl_cert != 'null' and ssl_key != 'null':
        cert_path = str(ssl_cert).strip("'\"")
        key_path = str(ssl_key).strip("'\"")
        if os.path.exists(cert_path) and os.path.exists(key_path):
            ssl_context = (cert_path, key_path)
            protocol = "https"
        else:
            print(f"  [WARN] SSL files not found: {cert_path}")
            protocol = "http"
    else:
        protocol = "http"

    print(f"\n  Dune Awakening Dashboard")
    print(f"  {protocol}://{host}:{port}")
    print(f"  Debug: {debug}")
    if ssl_context:
        print(f"  SSL: Enabled\n")
    else:
        print(f"  SSL: Disabled (use http:// not https://)\n")

    socketio.run(app, host=host, port=port, debug=debug, log_output=False, ssl_context=ssl_context)

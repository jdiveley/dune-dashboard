"""Item package service — predefined item bundles for bulk inventory injection."""

import logging

logger = logging.getLogger(__name__)


class PackageService:
    def __init__(self, db):
        self.db = db

    def list_packages(self):
        return self.db.query("""
            SELECT p.id, p.name, p.description, p.created_at,
                   COUNT(i.id)::int AS item_count
            FROM dashboard.item_packages p
            LEFT JOIN dashboard.item_package_items i ON i.package_id = p.id
            GROUP BY p.id
            ORDER BY p.name
        """)

    def get_package(self, package_id):
        pkg = self.db.query(
            "SELECT * FROM dashboard.item_packages WHERE id = %s",
            [package_id], one=True
        )
        if not pkg:
            return None, []
        items = self.db.query(
            "SELECT * FROM dashboard.item_package_items WHERE package_id = %s ORDER BY id",
            [package_id]
        )
        return pkg, items

    def create_package(self, name, description=''):
        name = name.strip()
        if not name:
            return False, "Name is required"
        conn = self.db.get_connection()
        if not conn:
            return False, "Database connection failed"
        bad = False
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO dashboard.item_packages (name, description) VALUES (%s, %s) RETURNING id",
                [name, description.strip()]
            )
            row = cur.fetchone()
            conn.commit()
            pkg_id = row[0] if isinstance(row, (tuple, list)) else row['id']
            logger.info(f"Created item package id={pkg_id} name={name!r}")
            return True, pkg_id
        except Exception as e:
            bad = True
            if conn:
                conn.rollback()
            logger.error(f"Failed to create package: {e}")
            return False, str(e)
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn, bad=bad)

    def update_package(self, package_id, name, description=''):
        name = name.strip()
        if not name:
            return False, "Name is required"
        conn = self.db.get_connection()
        if not conn:
            return False, "Database connection failed"
        bad = False
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE dashboard.item_packages SET name = %s, description = %s WHERE id = %s",
                [name, description.strip(), package_id]
            )
            conn.commit()
            return True, None
        except Exception as e:
            bad = True
            if conn:
                conn.rollback()
            logger.error(f"Failed to update package {package_id}: {e}")
            return False, str(e)
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn, bad=bad)

    def delete_package(self, package_id):
        conn = self.db.get_connection()
        if not conn:
            return False, "Database connection failed"
        bad = False
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM dashboard.item_packages WHERE id = %s", [package_id])
            conn.commit()
            return True, None
        except Exception as e:
            bad = True
            if conn:
                conn.rollback()
            logger.error(f"Failed to delete package {package_id}: {e}")
            return False, str(e)
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn, bad=bad)

    def add_item(self, package_id, template_id, display_name='', item_type='resource', stack_size=1, quality_level=0):
        if not template_id:
            return False, "template_id is required"
        conn = self.db.get_connection()
        if not conn:
            return False, "Database connection failed"
        bad = False
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM dashboard.item_packages WHERE id = %s", [package_id])
            if not cur.fetchone():
                return False, "Package not found"
            cur.execute(
                """INSERT INTO dashboard.item_package_items
                   (package_id, template_id, display_name, item_type, stack_size, quality_level)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                [package_id, template_id, display_name.strip(), item_type, max(1, int(stack_size)), max(0, int(quality_level))]
            )
            row = cur.fetchone()
            conn.commit()
            item_id = row[0] if isinstance(row, (tuple, list)) else row['id']
            return True, item_id
        except Exception as e:
            bad = True
            if conn:
                conn.rollback()
            logger.error(f"Failed to add item to package {package_id}: {e}")
            return False, str(e)
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn, bad=bad)

    def remove_item(self, item_id):
        conn = self.db.get_connection()
        if not conn:
            return False, "Database connection failed"
        bad = False
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM dashboard.item_package_items WHERE id = %s", [item_id])
            conn.commit()
            return True, None
        except Exception as e:
            bad = True
            if conn:
                conn.rollback()
            logger.error(f"Failed to remove package item {item_id}: {e}")
            return False, str(e)
        finally:
            if cur:
                cur.close()
            self.db.return_connection(conn, bad=bad)

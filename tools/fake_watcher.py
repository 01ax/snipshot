"""A minimal org.kde.StatusNotifierWatcher so tray icons can be tested in the private headless session (the real
desktop gets this from its AppIndicator extension, which the private session does not have). Started by
headless_session.sh; it only keeps the list of registered items."""
from gi.repository import Gio, GLib

XML = """
<node><interface name="org.kde.StatusNotifierWatcher">
  <method name="RegisterStatusNotifierItem"><arg type="s" name="service" direction="in"/></method>
  <method name="RegisterStatusNotifierHost"><arg type="s" name="service" direction="in"/></method>
  <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
  <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
  <property name="ProtocolVersion" type="i" access="read"/>
  <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
  <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
</interface></node>"""

items = []
conn_ref = []


def on_call(conn, sender, path, iface, method, params, inv):
    if method == "RegisterStatusNotifierItem":
        name = params.unpack()[0]
        if name not in items:
            items.append(name)
            conn.emit_signal(None, path, iface, "StatusNotifierItemRegistered", GLib.Variant("(s)", (name,)))
    inv.return_value(None)


def on_get(conn, sender, path, iface, prop):
    return {"RegisteredStatusNotifierItems": GLib.Variant("as", items),
            "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
            "ProtocolVersion": GLib.Variant("i", 0)}.get(prop)


def acquired(conn, name):
    conn_ref.append(conn)
    conn.register_object("/StatusNotifierWatcher", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], on_call, on_get, None)


Gio.bus_own_name(Gio.BusType.SESSION, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, acquired, None, None)
GLib.MainLoop().run()

"""System-tray icon for Snipshot using the StatusNotifierItem + dbusmenu D-Bus protocols.

This is what GNOME's AppIndicator support (and your ^ tray menu) lists. It needs only Gio, no extra packages.
The menu is a flat list of items: ``{"label": str, "callback": callable}``, ``None`` for a separator.
"""
import os

from gi.repository import Gio, GLib

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <method name="ContextMenu"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="Activate"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="Scroll"><arg type="i" name="delta" direction="in"/><arg type="s" name="orientation" direction="in"/></method>
    <signal name="NewTitle"/><signal name="NewIcon"/><signal name="NewStatus"><arg type="s" name="status"/></signal>
    <signal name="NewToolTip"/>
  </interface>
</node>"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/><arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/><arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/><arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/><arg type="s" name="name" direction="in"/><arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/><arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/><arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/><arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" name="id" direction="in"/><arg type="b" name="needUpdate" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/><arg type="ai" name="updatesNeeded" direction="out"/><arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})" name="updatedProps"/><arg type="a(ias)" name="removedProps"/></signal>
    <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
    <signal name="ItemActivationRequested"><arg type="i" name="id"/><arg type="u" name="timestamp"/></signal>
  </interface>
</node>"""

WATCHER = ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher")
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"


class TrayIcon:
    _counter = 0

    def __init__(self, title, icon_name, items, icon_theme_path="", on_activate=None, app_id="snipshot"):
        TrayIcon._counter += 1
        self.title, self.icon_name, self.icon_theme_path = title, icon_name, icon_theme_path
        self.items = list(items)
        self.on_activate = on_activate
        self.app_id = app_id
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-{TrayIcon._counter}"
        self.revision = 1
        self.registered = False
        self.conn = None
        self._owner_id = 0
        self._watch_id = 0
        self._reg_ids = []

    # -- lifecycle
    def start(self):
        """Own our bus name, export the objects and register with the watcher (re-registers if it restarts)."""
        self._owner_id = Gio.bus_own_name(Gio.BusType.SESSION, self.bus_name, Gio.BusNameOwnerFlags.NONE,
                                          self._bus_acquired, None, None)
        self._watch_id = Gio.bus_watch_name(Gio.BusType.SESSION, WATCHER[0], Gio.BusNameWatcherFlags.NONE,
                                            lambda *_: self._register(), lambda *_: setattr(self, "registered", False))

    def stop(self):
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
        if self.conn:
            for rid in self._reg_ids:
                self.conn.unregister_object(rid)
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
        self._reg_ids, self.conn, self._owner_id, self._watch_id = [], None, 0, 0

    def set_items(self, items):
        self.items = list(items)
        self.revision += 1
        if self.conn:
            self.conn.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                                  GLib.Variant("(ui)", (self.revision, 0)))

    # -- D-Bus plumbing
    def _bus_acquired(self, conn, _name):
        self.conn = conn
        item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._reg_ids.append(conn.register_object(ITEM_PATH, item_info, self._item_call, self._item_get, None))
        self._reg_ids.append(conn.register_object(MENU_PATH, menu_info, self._menu_call, self._menu_get, None))
        self._register()

    def _register(self):
        if not self.conn:
            return

        def done(conn, res):
            try:
                conn.call_finish(res)
                self.registered = True
            except GLib.Error:
                self.registered = False
        self.conn.call(WATCHER[0], WATCHER[1], WATCHER[2], "RegisterStatusNotifierItem",
                       GLib.Variant("(s)", (self.bus_name,)), None, Gio.DBusCallFlags.NONE, 3000, None, done)

    def _item_get(self, _c, _s, _p, _i, prop):
        tooltip = GLib.Variant("(sa(iiay)ss)", ("", [], self.title, ""))
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"), "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self.title), "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0), "IconName": GLib.Variant("s", self.icon_name),
            "IconThemePath": GLib.Variant("s", self.icon_theme_path),
            "OverlayIconName": GLib.Variant("s", ""), "AttentionIconName": GLib.Variant("s", ""),
            "ItemIsMenu": GLib.Variant("b", True), "Menu": GLib.Variant("o", MENU_PATH), "ToolTip": tooltip,
        }
        return values.get(prop)

    def _item_call(self, _c, _s, _p, _i, method, params, inv):
        if method in ("Activate", "SecondaryActivate") and self.on_activate:
            GLib.idle_add(self.on_activate)
        inv.return_value(None)

    # dbusmenu ---------------------------------------------------------------
    def _props(self, idx):
        """Properties of item idx (1-based into self.items); id 0 is the root."""
        if idx == 0:
            return {"children-display": GLib.Variant("s", "submenu")}
        it = self.items[idx - 1]
        if it is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", it["label"]), "enabled": GLib.Variant("b", it.get("enabled", True)),
                "visible": GLib.Variant("b", True)}

    def _layout(self, parent):
        if parent == 0:
            kids = [GLib.Variant("(ia{sv}av)", (i + 1, self._props(i + 1), [])) for i in range(len(self.items))]
            return (0, self._props(0), kids)
        return (parent, self._props(parent), [])

    def _menu_get(self, _c, _s, _p, _i, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}.get(prop)

    def _menu_call(self, _c, _s, _p, _i, method, params, inv):
        a = params.unpack() if params is not None else ()
        if method == "GetLayout":
            inv.return_value(GLib.Variant("(u(ia{sv}av))", (self.revision, self._layout(a[0]))))
        elif method == "GetGroupProperties":
            ids = a[0] or list(range(len(self.items) + 1))
            inv.return_value(GLib.Variant("(a(ia{sv}))", ([(i, self._props(i)) for i in ids
                                                          if 0 <= i <= len(self.items)],)))
        elif method == "GetProperty":
            inv.return_value(GLib.Variant("(v)", (self._props(a[0]).get(a[1], GLib.Variant("s", "")),)))
        elif method == "Event":
            self._event(a[0], a[1])
            inv.return_value(None)
        elif method == "EventGroup":
            for idx, ev, _data, _ts in a[0]:
                self._event(idx, ev)
            inv.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            inv.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            inv.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            inv.return_value(None)

    def _event(self, idx, event):
        if event == "clicked" and 1 <= idx <= len(self.items):
            it = self.items[idx - 1]
            if it and it.get("callback") and it.get("enabled", True):
                GLib.idle_add(it["callback"])

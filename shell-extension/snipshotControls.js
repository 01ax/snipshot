// Snipshot recording controls for GNOME Shell.
//
// While Snipshot records the screen this adds, next to GNOME's own orange "screen is being shared" button:
//   - a small orange pill with the running time and three icon buttons: pause / resume, stop and save, and delete
//     (the recording goes to the Trash), each with a hover tooltip, and
//   - "Pause recording" / "Stop recording" tiles in the quick settings popup.
// Everything talks to Snipshot through its D-Bus actions (org.gtk.Actions on local.snipshot[.dev]); nothing is
// sent or stored anywhere else, and nothing here touches GNOME's own indicators. Only GNOME's public extension
// interfaces are used (St widgets, quick settings items, panel boxes).
//
// Used by both the standalone extension (extension.js in this folder) and by other extensions that want to include
// it: `const c = new SnipshotControls(); c.enable(); ... c.disable();`

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

// [D-Bus name, object path] of Snipshot's action group: the normal install, then the side-by-side dev copy.
const SNIPSHOT_APPS = [['local.snipshot', '/local/snipshot'], ['local.snipshot.dev', '/local/snipshot/dev']];
const TOOLTIP_DELAY_MS = 350;

export class SnipshotControls {
    enable() {
        this._groups = new Map();
        this._watches = [];
        this._tip = null;
        this._tipTimer = 0;
        this._buildInline();
        this._buildTiles();
        for (const [name, path] of SNIPSHOT_APPS) {
            this._watches.push(Gio.bus_watch_name(Gio.BusType.SESSION, name, Gio.BusNameWatcherFlags.NONE,
                () => this._appeared(name, path), () => this._vanished(name)));
        }
        this._sync();
    }

    disable() {
        for (const id of this._watches ?? [])
            Gio.bus_unwatch_name(id);
        this._watches = [];
        for (const name of [...(this._groups?.keys() ?? [])])
            this._vanished(name, false);
        this._hideTip();
        this._inline?.destroy();
        this._inline = null;
        this._pauseTile?.destroy();
        this._stopTile?.destroy();
        this._tileIndicator?.destroy();
        this._pauseTile = this._stopTile = this._tileIndicator = null;
        this._groups = null;
    }

    // ---- talking to Snipshot ------------------------------------------------------------------------------

    _appeared(name, path) {
        const group = Gio.DBusActionGroup.get(Gio.DBus.session, name, path);
        group.list_actions();                     // starts the subscription; later changes arrive as signals
        group._snipshotIds = ['action-added', 'action-state-changed', 'action-removed'].map(sig => group.connect(sig, () => this._sync()));
        this._groups.set(name, group);
        this._sync();
    }

    _vanished(name, sync = true) {
        const group = this._groups?.get(name);
        if (group?._snipshotIds)
            for (const id of group._snipshotIds)
                group.disconnect(id);
        this._groups?.delete(name);
        if (sync)
            this._sync();
    }

    /** {group, state: 'recording' | 'paused', time: 'mm:ss'} for the Snipshot that is recording, or null. */
    _current() {
        for (const [, group] of this._groups ?? []) {
            try {
                if (!group.has_action('recording-state'))
                    continue;
                const state = group.get_action_state('recording-state')?.get_string()[0];
                if (state === 'recording' || state === 'paused')
                    return {group, state, time: group.get_action_state('recording-time')?.get_string()[0] ?? ''};
            } catch (e) {
                // the program went away between the check and the read
            }
        }
        return null;
    }

    _act(action) {
        this._current()?.group.activate_action(action, null);
    }

    // ---- the pill next to GNOME's orange button ---------------------------------------------------------------

    _buildInline() {
        const box = new St.BoxLayout({style_class: 'snipshot-controls', visible: false});
        this._time = new St.Label({style_class: 'snipshot-controls-time', y_align: Clutter.ActorAlign.CENTER, text: ''});
        box.add_child(this._time);
        this._pauseButton = this._makeButton('media-playback-pause-symbolic', () => this._current()?.state === 'paused' ? 'Resume recording' : 'Pause recording', 'pause-recording');
        this._stopButton = this._makeButton('media-playback-stop-symbolic', () => 'Stop recording and save it', 'stop-recording');
        this._deleteButton = this._makeButton('user-trash-symbolic', () => 'Delete recording (moves it to the Trash)', 'discard-recording');
        for (const b of [this._pauseButton, this._stopButton, this._deleteButton])
            box.add_child(b);
        this._inline = box;
    }

    _makeButton(iconName, tipText, action) {
        const button = new St.Button({
            style_class: 'snipshot-controls-button',
            reactive: true,
            can_focus: true,
            track_hover: true,
            y_align: Clutter.ActorAlign.CENTER,
            child: new St.Icon({icon_name: iconName, style_class: 'snipshot-controls-icon'}),
        });
        button.connect('clicked', () => {
            this._hideTip();
            this._act(action);
        });
        button.connect('notify::hover', () => {
            if (button.hover)
                this._showTipSoon(button, tipText);
            else
                this._hideTip();
        });
        button.connect('destroy', () => this._hideTip());
        button._tipText = tipText;
        return button;
    }

    /** Put our pill just LEFT of GNOME's orange screen-sharing button and tuck its right end underneath that button, so
     * the two read as one long orange pill that has expanded to the left. Panel items sit in a box inside a St.Bin
     * ("container"); our pill must be a sibling of that container, not of the button itself. */
    _place() {
        const box = this._inline;
        const button = Main.panel.statusArea?.screenSharing;
        const anchor = button?.container ?? button;
        const parent = anchor?.get_parent() ?? Main.panel._rightBox;
        if (!parent)
            return;
        if (box.get_parent() !== parent) {
            box.get_parent()?.remove_child(box);
            if (anchor?.get_parent() === parent)
                parent.insert_child_below(box, anchor);
            else
                parent.insert_child_at_index(box, 0);
        } else if (anchor?.get_parent() === parent) {
            const kids = parent.get_children();
            if (kids[kids.indexOf(anchor) - 1] !== box)
                parent.set_child_below_sibling(box, anchor);
        }
        // Match GNOME's button: its colour (so it works in any theme), its height, and slide under half of its width.
        // The shell's theme paints that button with an inset box-shadow inside a transparent border, so copy that.
        let style = '';
        let overlap = 0;
        if (button) {
            try {
                const shadow = button.get_theme_node().get_box_shadow();
                if (shadow) {
                    const c = shadow.color;
                    style += `box-shadow: inset 0 0 0 100px rgba(${c.red}, ${c.green}, ${c.blue}, ${c.alpha / 255}); `;
                }
            } catch (e) {
                // keep the stylesheet's colour
            }
            const h = Math.round(button.height);
            if (button.visible && h > 0) {
                // Tuck our rounded right end completely under the flat part of GNOME's button (its own round end is
                // then drawn over our body), so the join has no notch.
                const border = button.get_theme_node().get_border_width(St.Side.TOP);
                overlap = Math.max(0, Math.min(h - 2 * border, Math.round(button.width) - 10));
                box.set_height(h);
                style += `padding-right: ${overlap + 6}px; `;
            }
        }
        box.translation_x = overlap;
        box.style = style;
    }

    // ---- tooltips (GNOME's own dash-label look) ---------------------------------------------------------------

    _showTipSoon(button, tipText) {
        this._hideTip();
        this._tipTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TOOLTIP_DELAY_MS, () => {
            this._tipTimer = 0;
            this._showTip(button, tipText());
            return GLib.SOURCE_REMOVE;
        });
    }

    _showTip(button, text) {
        this._hideTip();
        const label = new St.Label({style_class: 'dash-label snipshot-tooltip', text, opacity: 0});
        Main.uiGroup.add_child(label);
        const [x, y] = button.get_transformed_position();
        const [w, h] = button.get_transformed_size();
        const [lw, lh] = label.get_size();
        const monitor = Main.layoutManager.findMonitorForActor(button);
        let lx = Math.round(x + (w - lw) / 2);
        if (monitor)
            lx = Math.max(monitor.x + 4, Math.min(lx, monitor.x + monitor.width - lw - 4));
        const above = monitor && y > monitor.y + monitor.height / 2;     // a bottom taskbar: tooltip above it
        label.set_position(lx, Math.round(above ? y - lh - 6 : y + h + 6));
        label.ease({opacity: 255, duration: 120, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        this._tip = label;
    }

    _hideTip() {
        if (this._tipTimer) {
            GLib.source_remove(this._tipTimer);
            this._tipTimer = 0;
        }
        this._tip?.destroy();
        this._tip = null;
    }

    // ---- tiles in the quick settings popup -------------------------------------------------------------------

    _buildTiles() {
        const quickSettings = Main.panel.statusArea?.quickSettings;
        if (!quickSettings?.addExternalIndicator)
            return;
        this._pauseTile = new QuickToggle({title: 'Pause recording', iconName: 'media-playback-pause-symbolic', toggleMode: true});
        this._stopTile = new QuickToggle({title: 'Stop recording', iconName: 'media-playback-stop-symbolic', toggleMode: false});
        this._pauseTile.visible = this._stopTile.visible = false;
        this._pauseTile.connect('clicked', () => this._act('pause-recording'));
        this._stopTile.connect('clicked', () => {
            this._act('stop-recording');
            quickSettings.menu.close();
        });
        this._tileIndicator = new SystemIndicator();
        this._tileIndicator.quickSettingsItems.push(this._pauseTile, this._stopTile);
        quickSettings.addExternalIndicator(this._tileIndicator);
    }

    // ---- keeping everything in step with Snipshot ----------------------------------------------------------------

    _sync() {
        const box = this._inline;
        if (!box || !this._groups)
            return;
        const now = this._current();
        if (this._pauseTile) {
            this._pauseTile.visible = this._stopTile.visible = !!now;
        }
        if (!now) {
            this._hideTip();
            if (box.visible)
                box.ease({
                    opacity: 0, duration: 150, mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    onComplete: () => {
                        if (!this._current())
                            box.hide();
                    },
                });
            return;
        }
        const paused = now.state === 'paused';
        this._time.text = paused ? `Paused ${now.time}` : now.time;
        paused ? box.add_style_class_name('snipshot-paused') : box.remove_style_class_name('snipshot-paused');
        this._pauseButton.child.icon_name = paused ? 'media-playback-start-symbolic' : 'media-playback-pause-symbolic';
        this._pauseButton.accessible_name = paused ? 'Resume recording' : 'Pause recording';
        this._stopButton.accessible_name = 'Stop recording and save it';
        this._deleteButton.accessible_name = 'Delete recording';
        if (this._pauseTile) {
            this._pauseTile.title = paused ? 'Resume recording' : 'Pause recording';
            this._pauseTile.iconName = paused ? 'media-playback-start-symbolic' : 'media-playback-pause-symbolic';
            this._pauseTile.checked = paused;
            this._stopTile.subtitle = paused ? `Paused at ${now.time}` : `Recording ${now.time}`;
        }
        this._place();
        if (!box.visible || box.opacity < 255) {
            if (!box.visible)
                box.opacity = 0;
            box.show();
            box.ease({opacity: 255, duration: 200, mode: Clutter.AnimationMode.EASE_OUT_QUAD});    // "expands" into view
        }
    }
}

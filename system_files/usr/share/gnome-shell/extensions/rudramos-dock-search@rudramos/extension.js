// RudramOS: a search box at the left end of the dock (Dash to Dock, horizontal only). Typing lists
// the matching apps above it; click one, or pick it with Up/Down and Enter, to open it. Escape,
// clicking outside or switching to a window closes the list. Every dock (one per monitor) gets
// its own box, also when Dash to Dock rebuilds its docks after a settings change. If Dash to Dock
// is off or its layout changes, there is simply no box and the dock works as usual.
import Clutter from 'gi://Clutter';
import GioUnix from 'gi://GioUnix';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DOCK_NAME = 'dashtodockContainer';
const MAX_RESULTS = 8;
const ICON_SIZE = 24;
const GAP = 8;

// Installed apps matching `query`, best first (the same matching GNOME's own app search uses:
// name, generic name, keywords and command)
export function searchApps(query) {
    const appSystem = Shell.AppSystem.get_default();
    const apps = [];
    for (const group of GioUnix.DesktopAppInfo.search(query)) {
        for (const id of group) {
            const app = appSystem.lookup_app(id);
            if (app?.get_app_info()?.should_show() && !apps.includes(app))
                apps.push(app);
            if (apps.length === MAX_RESULTS)
                return apps;
        }
    }
    return apps;
}

class DockSearch {
    constructor(dash) {
        this._rows = [];
        this._selected = -1;

        this.entry = new St.Entry({
            style_class: 'rudramos-dock-search',
            hint_text: 'Search apps',
            can_focus: true,
            track_hover: true,
            y_align: Clutter.ActorAlign.CENTER,
            primary_icon: new St.Icon({icon_name: 'edit-find-symbolic', style_class: 'popup-menu-icon'}),
        });
        const text = this.entry.clutter_text;
        text.connectObject(
            'text-changed', () => this._update(),
            'key-press-event', (_actor, event) => this._onKeyPress(event),
            'key-focus-in', () => this._update(),
            'key-focus-out', () => this.close(),
            this);

        this.results = new St.BoxLayout({
            style_class: 'rudramos-dock-search-results',
            orientation: Clutter.Orientation.VERTICAL,
            visible: false,
        });
        Main.layoutManager.addTopChrome(this.results);

        // Switching to a window (click, Alt+Tab) takes focus from the box: close the list
        global.display.connectObject('notify::focus-window', () => {
            if (global.display.focus_window)
                this.close();
        }, this);

        // Keep the box first: Dash to Dock moves its apps button to the front when settings change
        const container = dash._dashContainer;
        container.insert_child_at_index(this.entry, 0);
        container.connectObject('notify::first-child', () => {
            if (container.first_child !== this.entry)
                container.set_child_below_sibling(this.entry, null);
        }, this);
        // The dock destroys the box along with itself
        this.entry.connect('destroy', () => {
            this.entry = null;
            this.destroy();
        });
    }

    destroy() {
        global.display.disconnectObject(this);
        if (this.entry) {
            this.entry.get_parent()?.disconnectObject(this);
            this.entry.destroy();
        }
        if (this.results) {
            Main.layoutManager.removeChrome(this.results);
            this.results.destroy();
            this.results = null;
        }
    }

    close() {
        if (!this.entry)
            return;
        if (this.entry.text)
            this.entry.text = '';
        this.results.hide();
        if (this.entry.clutter_text.has_key_focus())
            global.stage.set_key_focus(null);
    }

    _onKeyPress(event) {
        switch (event.get_key_symbol()) {
        case Clutter.KEY_Escape:
            this.close();
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Down:
            this._select(this._selected + 1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Up:
            this._select(this._selected - 1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Return:
        case Clutter.KEY_KP_Enter:
        case Clutter.KEY_ISO_Enter:
            if (this._rows[this._selected])
                this._open(this._rows[this._selected].app);
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _update() {
        const query = this.entry.text.trim();
        this.results.destroy_all_children();
        this._rows = [];
        this._selected = -1;
        if (!query) {
            this.results.hide();
            return;
        }

        const apps = searchApps(query);
        for (const app of apps) {
            const box = new St.BoxLayout({style_class: 'rudramos-dock-search-result-box', x_expand: true});
            box.add_child(app.create_icon_texture(ICON_SIZE));
            box.add_child(new St.Label({text: app.get_name(), y_align: Clutter.ActorAlign.CENTER}));
            const row = new St.Button({
                style_class: 'rudramos-dock-search-result',
                child: box,
                x_expand: true,
                can_focus: false,
                track_hover: true,
            });
            row.app = app;
            row.connect('clicked', () => this._open(app));
            this.results.add_child(row);
            this._rows.push(row);
        }
        if (!apps.length)
            this.results.add_child(new St.Label({style_class: 'rudramos-dock-search-empty', text: 'No apps found'}));
        this._select(0);
        this.results.show();
        this._place();
    }

    _select(index) {
        if (!this._rows.length)
            return;
        this._rows[this._selected]?.remove_style_pseudo_class('selected');
        this._selected = (index + this._rows.length) % this._rows.length;
        this._rows[this._selected].add_style_pseudo_class('selected');
    }

    // Above the box (below it if the dock is at the top), inside the dock's monitor
    _place() {
        const [x, y] = this.entry.get_transformed_position();
        const [, width] = this.results.get_preferred_width(-1);
        const [, height] = this.results.get_preferred_height(width);
        const monitor = Main.layoutManager.findMonitorForActor(this.entry) ?? Main.layoutManager.primaryMonitor;
        let top = y - height - GAP;
        if (top < monitor.y)
            top = y + this.entry.height + GAP;
        const left = Math.min(Math.max(x, monitor.x + GAP), monitor.x + monitor.width - width - GAP);
        this.results.set_position(Math.round(left), Math.round(top));
    }

    _open(app) {
        this.close();
        app.activate();
    }
}

export default class DockSearchExtension extends Extension {
    enable() {
        this._searches = new Map();
        Main.layoutManager.uiGroup.connectObject('child-added', (_group, actor) => this._addTo(actor), this);
        for (const actor of Main.layoutManager.uiGroup.get_children())
            this._addTo(actor);
    }

    disable() {
        Main.layoutManager.uiGroup.disconnectObject(this);
        for (const [dock, search] of this._searches) {
            dock.disconnectObject(this);
            search.destroy();
        }
        this._searches = null;
    }

    // Dash to Dock adds each dock to the UI group, and again when it is rebuilt or (un)fixed
    _addTo(dock) {
        const dash = dock.name === DOCK_NAME ? dock.dash : null;
        if (!dash?._isHorizontal || !dash._dashContainer || this._searches.has(dock))
            return;
        this._searches.set(dock, new DockSearch(dash));
        dock.connectObject('destroy', () => this._searches?.delete(dock), this);
    }
}

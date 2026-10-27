// RudramOS: the login screen (GDM) shows the RudramOS art instead of GNOME's plain colour.
// GNOME 50 paints that background from code (Background.SystemBackground), not from the theme,
// so this sets an image on it: on backgrounds already shown when the extension starts, and on
// every one created later. Runs only on the login screen ("session-modes": ["gdm"]). If anything
// fails, GNOME keeps its plain background and login works as usual.
import Gio from 'gi://Gio';
import GDesktopEnums from 'gi://GDesktopEnums';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';

const IMAGE = '/usr/share/pcos/login-background.jpg';

function setImage(actor, file) {
    const background = actor?.content?.background;
    if (background)
        background.set_file(file, GDesktopEnums.BackgroundStyle.ZOOM);
}

function systemBackgrounds() {
    return global.stage.get_children().filter(a => a instanceof Background.SystemBackground);
}

export default class LoginBackground extends Extension {
    enable() {
        const file = Gio.File.new_for_path(IMAGE);
        if (!file.query_exists(null))
            return;
        this._injections = new InjectionManager();
        this._injections.overrideMethod(Background.SystemBackground.prototype, '_init', original => {
            return function (...args) {
                original.call(this, ...args);
                setImage(this, file);
            };
        });
        for (const actor of systemBackgrounds())
            setImage(actor, file);
    }

    disable() {
        this._injections?.clear();
        this._injections = null;
        for (const actor of systemBackgrounds())
            setImage(actor, null);
    }
}

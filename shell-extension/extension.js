// Snipshot recording controls: the standalone extension. All the work is in snipshotControls.js.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {SnipshotControls} from './snipshotControls.js';

export default class SnipshotControlsExtension extends Extension {
    enable() {
        this._controls = new SnipshotControls();
        this._controls.enable();
    }

    disable() {
        this._controls?.disable();
        this._controls = null;
    }
}

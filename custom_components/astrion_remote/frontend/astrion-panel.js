// Astrion Remote: visual editor for the remote's buttons and pages (Home Assistant sidebar panel).
// Plain ES module, no build step, no external resources. Uses Home Assistant's own elements
// (ha-card, ha-selector, ha-button, ha-icon-button, ha-expansion-panel) with plain fallbacks.

const WS = "astrion_remote";

const GESTURES = [
  ["tap", "Tap"],
  ["double", "Double tap"],
  ["hold", "Hold"],
];

const ACTION_TYPES = [
  ["tv_key", "TV key"],
  ["ha", "Home Assistant action"],
  ["page", "Go to page"],
  ["event", "Event only (use in automations)"],
  ["none", "Nothing"],
  ["app", "App command"],
  ["voice", "Voice"],
  ["choose", "Choose from list"],
];

const CHOOSE_DOMAINS = ["select", "input_select"];

// visible_if: section shown only while the entity's state is (not) one of these.
const VISIBLE_MODES = [
  ["state_not", "is not one of"],
  ["state_in", "is one of"],
];
const COMMON_STATES = ["off", "on", "idle", "standby", "unavailable", "playing", "paused", "buffering", "unknown"];

const VOICE_TARGETS = [
  ["ha", "Home Assistant Assist"],
  ["tv", "TV Google Assistant"],
];

const TV_HOLD_MODES = [
  ["passthrough", "Real hold (press and release)"],
  ["repeat", "Repeat while held"],
  ["none", "None (ignore hold)"],
];

// tv.transport: how tv_key actions reach the TV. Absent = auto; apps that do not know a value use auto.
const TV_TRANSPORTS = [
  ["auto", "Auto (direct when paired, else Control Freak)"],
  ["atv", "Android TV Remote (direct)"],
  ["controlfreak", "Control Freak (MQTT)"],
  ["bluetooth", "Bluetooth"],
];
const BLUETOOTH_WARNING = "Bluetooth slows the remote's Wi-Fi while connected.";

const APP_CMDS = [
  ["settings", "Open settings"],
  ["reload", "Reload config"],
];

const SECTION_TYPES = [
  ["now_playing", "Now playing"],
  ["tiles", "Tiles"],
  ["segmented", "Segmented"],
  ["slider", "Slider"],
  ["rocker", "Rocker"],
  ["switch", "Switch"],
  ["keys", "Keys"],
];

const SECTION_ENTITY_DOMAINS = {
  now_playing: ["media_player"],
  segmented: ["select", "input_select"],
  slider: ["number", "light"],
  rocker: ["light"],
  switch: ["switch", "light", "input_boolean", "fan"],
};

// Physical layout, top to bottom.
const LAYOUT = [
  ["row3", ["back", "home", "power"]],
  ["row1", ["voice"]],
  ["dpad", ["up", "left", "ok", "right", "down"]],
  ["row1", ["menu"]],
  ["row2", ["page_up", "page_down"]],
  ["row3", ["vol_up", "vol_down", "mute"]],
  ["row4", ["red", "green", "blue", "yellow"]],
  ["row4", ["sc1", "sc2", "sc3", "sc4"]],
];

const KEY_COLORS = { red: "#e53935", green: "#43a047", blue: "#1e88e5", yellow: "#fdd835" };
const KEY_ICONS = {
  back: "mdi:arrow-left",
  home: "mdi:home-outline",
  power: "mdi:power",
  voice: "mdi:microphone",
  up: "mdi:chevron-up",
  down: "mdi:chevron-down",
  left: "mdi:chevron-left",
  right: "mdi:chevron-right",
  menu: "mdi:menu",
  page_up: "mdi:chevron-double-up",
  page_down: "mdi:chevron-double-down",
  vol_up: "mdi:volume-plus",
  vol_down: "mdi:volume-minus",
  mute: "mdi:volume-mute",
  sc1: "mdi:lightbulb-outline",
  sc2: "mdi:curtains",
  sc3: "mdi:music",
  sc4: "mdi:thermostat",
};

const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const arr = (v) => (Array.isArray(v) ? v : []);

/** Create an element: props are set as properties; "on:x" adds listeners; "@x" sets attributes. */
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on:")) el.addEventListener(k.slice(3), v);
    else if (k.startsWith("@")) {
      if (v !== false) el.setAttribute(k.slice(1), v === true ? "" : String(v));
    } else el[k] = v;
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const defined = (name) => !!customElements.get(name);

let _loading;
/** Home Assistant lazy-loads its form elements; pull them in the way custom cards do. */
function loadHaElements() {
  if (_loading) return _loading;
  _loading = (async () => {
    const wanted = ["ha-selector", "ha-expansion-panel"];
    if (wanted.every(defined)) return;
    try {
      if (window.loadCardHelpers) {
        const helpers = await window.loadCardHelpers();
        for (const type of ["entities", "tile"]) {
          const card = await helpers.createCardElement({ type, entities: [], entity: "sun.sun" });
          if (card?.constructor?.getConfigElement) await card.constructor.getConfigElement();
        }
      }
    } catch (_err) {
      /* fall back below */
    }
    try {
      if (!defined("ha-selector")) {
        await customElements.whenDefined("partial-panel-resolver");
        const ppr = document.createElement("partial-panel-resolver");
        const routes = ppr._getRoutes?.([{ component_name: "config", url_path: "a" }]);
        await routes?.routes?.a?.load?.();
        await customElements.whenDefined("ha-panel-config");
        const cfg = document.createElement("ha-panel-config");
        await cfg?.routerOptions?.routes?.automation?.load?.();
      }
    } catch (_err) {
      /* plain inputs are used as a fallback */
    }
    await Promise.race([
      Promise.all(wanted.map((n) => customElements.whenDefined(n))),
      new Promise((r) => setTimeout(r, 5000)),
    ]);
  })();
  return _loading;
}

function slug(text) {
  return (
    String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "page"
  );
}

function entityList(target) {
  const ids = target?.entity_id;
  return Array.isArray(ids) ? ids : ids ? [ids] : [];
}

/** Our `ha` action -> value for the action selector. */
function toSelectorAction(action) {
  if (!isObj(action) || action.type !== "ha" || !action.action) return [];
  const out = { action: action.action };
  if (isObj(action.target)) out.target = clone(action.target);
  if (isObj(action.data) && Object.keys(action.data).length) out.data = clone(action.data);
  return [out];
}

/** Action selector value -> our `ha` action (keeps unknown fields like repeat/label/icon). */
function fromSelectorAction(value, old) {
  const items = Array.isArray(value) ? value : isObj(value) ? [value] : [];
  const item = items.find((i) => isObj(i) && (i.action || i.service));
  const out = { ...(isObj(old) ? old : {}), type: "ha" };
  delete out.target;
  delete out.data;
  out.action = item ? item.action || item.service : "";
  if (item && isObj(item.target) && Object.keys(item.target).length) {
    const target = { ...item.target };
    if ("entity_id" in target) target.entity_id = entityList(target);
    out.target = target;
  }
  if (item && isObj(item.data) && Object.keys(item.data).length) out.data = clone(item.data);
  return { action: out, extra: items.length > 1 };
}

class AstrionRemotePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "buttons";
    this._selKey = "ok";
    this._selPage = 0;
    this._errors = [];
    this._warnings = []; // non-blocking lint: [{path, msg}]
    this._version = null; // version of the stored config this editor started from
    this._stale = false; // a save was rejected because someone else saved first
    this._entries = [];
    this._entryId = null;
    this._config = null;
    this._saved = null;
    this._keys = [];
    this._tvKeys = [];
    this._contexts = [];
    this._status = "loading";
    this._message = "";
    this._newCtx = "";
    this._newPageTitle = "";
    this._newSectionType = "tiles";
    this._yamlPending = undefined;
    this._onBeforeUnload = (ev) => {
      if (this._dirty) {
        ev.preventDefault();
        ev.returnValue = "";
      }
    };
  }

  // ---- Home Assistant panel API ---------------------------------------------------------
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._init();
      return;
    }
    for (const el of this.shadowRoot.querySelectorAll("ha-selector, ha-menu-button")) el.hass = hass;
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = value;
    const btn = this.shadowRoot.querySelector("ha-menu-button");
    if (btn) btn.narrow = value;
    this.toggleAttribute("narrow", !!value);
  }

  set panel(value) {
    this._panel = value;
  }

  set route(value) {
    this._route = value;
  }

  connectedCallback() {
    window.addEventListener("beforeunload", this._onBeforeUnload);
  }

  disconnectedCallback() {
    window.removeEventListener("beforeunload", this._onBeforeUnload);
  }

  // ---- data ------------------------------------------------------------------------------
  async _init() {
    this._renderShell();
    this._renderAll();
    try {
      await loadHaElements();
      const entries = await this._hass.callWS({ type: "config_entries/get", domain: WS });
      this._entries = arr(entries).filter((e) => e.domain === WS || !e.domain);
      if (!this._entries.length) {
        this._status = "empty";
        this._renderAll();
        return;
      }
      let stored = null;
      try {
        stored = localStorage.getItem("astrion_remote_entry");
      } catch (_err) {
        /* storage unavailable */
      }
      const pick = this._entries.find((e) => e.entry_id === stored) || this._entries[0];
      await this._load(pick.entry_id);
    } catch (err) {
      this._status = "error";
      this._message = err?.message || String(err);
      this._renderAll();
    }
  }

  async _load(entryId) {
    this._status = "loading";
    this._renderAll();
    try {
      const [data, tv] = await Promise.all([
        this._hass.callWS({ type: `${WS}/config/get`, entry_id: entryId }),
        this._hass.callWS({ type: `${WS}/tv_keys` }),
      ]);
      this._entryId = entryId;
      try {
        localStorage.setItem("astrion_remote_entry", entryId);
      } catch (_err) {
        /* storage unavailable */
      }
      this._config = isObj(data?.config) ? data.config : { pages: [] };
      this._saved = JSON.stringify(this._config);
      this._keys = arr(data?.keys);
      this._contexts = arr(data?.context_values).map(String);
      this._canUndo = !!data?.can_undo;
      this._version = typeof data?.version === "string" ? data.version : null;
      this._warnings = arr(data?.warnings);
      this._stale = false;
      this._tvKeys = arr(tv?.keys).map(String);
      this._errors = [];
      this._yamlPending = undefined;
      this._status = "ready";
    } catch (err) {
      this._status = "error";
      this._message = err?.message || String(err);
    }
    this._renderAll();
  }

  get _dirty() {
    return this._status === "ready" && JSON.stringify(this._config) !== this._saved;
  }

  _touched({ chips = false, pages = false } = {}) {
    this._renderFooter();
    if (chips && this._tab === "buttons") this._renderChips();
    if (pages && this._tab === "pages") this._renderPageList();
    clearTimeout(this._validateTimer);
    this._validateTimer = setTimeout(() => this._validate(true), 600);
  }

  async _validate(quiet) {
    if (this._status !== "ready") return false;
    try {
      const res = await this._hass.callWS({
        type: `${WS}/config/validate`,
        entry_id: this._entryId,
        config: this._config,
      });
      this._errors = arr(res?.errors);
      this._warnings = arr(res?.warnings);
    } catch (err) {
      this._errors = [{ path: [], msg: err?.message || String(err) }];
    }
    this._renderErrors();
    this._markErrors();
    this._markWarnings();
    this._renderFooter();
    if (!quiet && this._errors.length) this._message = "";
    return this._errors.length === 0;
  }

  async _save() {
    if (this._saving) return;
    this._saving = true;
    this._message = "";
    this._renderFooter();
    try {
      if (!(await this._validate(false))) return;
      const msg = { type: `${WS}/config/set`, entry_id: this._entryId, config: this._config };
      if (this._version) msg.version = this._version;
      const res = await this._hass.callWS(msg);
      this._config = isObj(res?.config) ? res.config : this._config;
      this._saved = JSON.stringify(this._config);
      if (typeof res?.version === "string") this._version = res.version;
      this._stale = false;
      this._message = "Saved and published";
      this._yamlPending = undefined;
      this._renderBody();
    } catch (err) {
      if (err?.code === "stale_config") {
        // Someone else (another tab, a dashboard card) saved since we loaded: nothing was stored.
        this._stale = true;
      } else {
        this._errors = [{ path: [], msg: err?.message || String(err) }];
        this._renderErrors();
      }
    } finally {
      this._saving = false;
      this._renderFooter();
    }
  }

  // ---- reset to defaults (stored and published server-side; one-step undo) -----------------
  _afterReset(res, message) {
    this._config = isObj(res?.config) ? res.config : this._config;
    this._saved = JSON.stringify(this._config);
    this._canUndo = !!res?.can_undo;
    if (typeof res?.version === "string") this._version = res.version;
    this._stale = false;
    this._errors = [];
    this._yamlPending = undefined;
    this._message = message;
    this._renderAll();
  }

  async _reset(part, question, done) {
    if (this._saving) return;
    const unsaved = this._dirty ? "\n\nYour unsaved changes will be discarded." : "";
    if (!confirm(question + unsaved)) return;
    this._saving = true;
    try {
      const res = await this._hass.callWS({ type: `${WS}/config/reset`, entry_id: this._entryId, parts: [part] });
      this._afterReset(res, done);
    } catch (err) {
      this._errors = [{ path: [], msg: err?.message || String(err) }];
      this._renderErrors();
    } finally {
      this._saving = false;
      this._renderFooter();
    }
  }

  async _undoReset() {
    if (this._saving) return;
    const unsaved = this._dirty ? "\n\nYour unsaved changes will be discarded." : "";
    if (!confirm("Restore your config as it was before the last reset? Changes saved since then are lost." + unsaved)) return;
    this._saving = true;
    try {
      const res = await this._hass.callWS({ type: `${WS}/config/undo_reset`, entry_id: this._entryId });
      this._afterReset(res, "Reset undone and published");
    } catch (err) {
      this._errors = [{ path: [], msg: err?.message || String(err) }];
      this._renderErrors();
    } finally {
      this._saving = false;
      this._renderFooter();
    }
  }

  _resetBar(part, label, question, done) {
    return h(
      "div",
      { class: "tab-head" },
      h("button", { class: "btn", "on:click": () => this._reset(part, question, done) }, label),
      this._canUndo ? h("button", { class: "btn", "on:click": () => this._undoReset() }, "Undo reset") : null
    );
  }

  _revert() {
    if (!this._dirty) return;
    this._config = JSON.parse(this._saved);
    this._errors = [];
    this._message = "";
    this._yamlPending = undefined;
    this._renderAll();
  }

  // ---- config helpers ----------------------------------------------------------------------
  get _pages() {
    if (!Array.isArray(this._config.pages)) this._config.pages = [];
    return this._config.pages;
  }

  _keyObj(id, create) {
    let keys = this._config.keys;
    if (!isObj(keys)) {
      if (!create) return undefined;
      keys = this._config.keys = {};
    }
    if (!isObj(keys[id])) {
      if (!create) return undefined;
      keys[id] = {};
    }
    return keys[id];
  }

  _gestureTarget(id, ctx, create) {
    const key = this._keyObj(id, create);
    if (!key) return undefined;
    if (ctx === null) return key;
    if (!isObj(key.contexts)) {
      if (!create) return undefined;
      key.contexts = {};
    }
    if (!isObj(key.contexts[ctx])) {
      if (!create) return undefined;
      key.contexts[ctx] = {};
    }
    return key.contexts[ctx];
  }

  _setGesture(id, ctx, gesture, action) {
    const target = this._gestureTarget(id, ctx, action !== undefined);
    if (!target) return;
    if (action === undefined) delete target[gesture];
    else target[gesture] = action;
    const keys = this._config.keys;
    if (ctx === null && isObj(keys) && isObj(keys[id]) && !Object.keys(keys[id]).length) delete keys[id];
    this._touched({ chips: true });
  }

  _keyLabel(id) {
    return this._keys.find((k) => k.id === id)?.label || id;
  }

  _pageLabel(id) {
    if (id === "next") return "Next page";
    if (id === "prev") return "Previous page";
    const page = this._pages.find((p) => p?.id === id);
    return page ? page.title || page.id : id;
  }

  _summary(action) {
    if (!isObj(action)) return "Not set";
    switch (action.type) {
      case "tv_key":
        return action.key ? `TV ${action.key}` : "TV key";
      case "ha": {
        const ents = entityList(action.target);
        const name = String(action.action || "action");
        if (!ents.length) return name;
        const first = ents[0];
        const friendly = this._hass?.states?.[first]?.attributes?.friendly_name || first.split(".").pop();
        const more = ents.length > 1 ? ` +${ents.length - 1}` : "";
        const [domain, service] = name.split(".");
        if (domain === "script" && service === "turn_on") return `${friendly}${more}`;
        return `${domain === first.split(".")[0] ? service : name} · ${friendly}${more}`;
      }
      case "page":
        return `→ ${this._pageLabel(action.page)}`;
      case "event":
        return "Event only";
      case "none":
        return "Nothing";
      case "app":
        return `App: ${action.cmd || ""}`;
      case "voice":
        return action.target === "tv" ? "Voice: TV Assistant" : "Voice: HA Assist";
      case "choose": {
        if (!action.entity) return "Choose from list";
        const friendly = this._hass?.states?.[action.entity]?.attributes?.friendly_name || action.entity.split(".").pop();
        return `Choose: ${action.title || friendly}`;
      }
      default:
        return String(action.type || "?");
    }
  }

  _errorsAt(prefix) {
    return this._errors.filter((e) => prefix.every((p, i) => arr(e.path)[i] === p));
  }

  _warningsAt(prefix) {
    return this._warnings.filter((w) => prefix.every((p, i) => arr(w.path)[i] === p));
  }

  /** Amber lint line(s) for everything under `prefix`; refreshed in place by _markWarnings. */
  _warnSlot(prefix) {
    const el = h("div", { class: "warn-slot", "@data-warn-path": JSON.stringify(prefix) });
    this._fillWarnSlot(el, prefix);
    return el;
  }

  _fillWarnSlot(el, prefix) {
    el.replaceChildren(
      ...this._warningsAt(prefix).map((w) => {
        const rest = arr(w.path).slice(prefix.length).filter((p) => p !== "entity");
        return h("div", { class: "warning-line" }, rest.length ? `${rest.join(" › ")}: ${w.msg}` : w.msg);
      })
    );
  }

  _markWarnings() {
    for (const el of this.shadowRoot.querySelectorAll("[data-warn-path]")) {
      this._fillWarnSlot(el, JSON.parse(el.dataset.warnPath));
    }
  }

  async _reloadStale() {
    if (this._dirty && !confirm("Reload the saved config? Your unsaved changes will be discarded.")) return;
    await this._load(this._entryId);
  }

  // ---- generic controls --------------------------------------------------------------------
  _sel(selector, value, onChange, opts = {}) {
    if (defined("ha-selector")) {
      return h("ha-selector", {
        hass: this._hass,
        selector,
        value,
        label: opts.label,
        helper: opts.helper,
        required: !!opts.required,
        class: opts.class,
        "on:value-changed": (ev) => {
          ev.stopPropagation();
          onChange(ev.detail?.value);
        },
      });
    }
    return this._fallback(selector, value, onChange, opts);
  }

  _fallback(selector, value, onChange, opts) {
    const label = (child) => h("label", { class: "fallback" }, opts.label ? h("span", {}, opts.label) : null, child);
    if (selector.boolean) {
      return label(h("input", { type: "checkbox", checked: !!value, "on:change": (e) => onChange(e.target.checked) }));
    }
    if (selector.select && selector.select.multiple) {
      return label(
        h("input", {
          value: arr(value).join(", "),
          placeholder: "comma separated",
          "on:change": (e) => onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean)),
        })
      );
    }
    if (selector.select) {
      const options = arr(selector.select.options).map((o) => (isObj(o) ? o : { value: o, label: o }));
      if (selector.select.custom_value) {
        const id = `dl${Math.random().toString(36).slice(2)}`;
        return label(
          h(
            "span",
            {},
            h("input", { value: value ?? "", "@list": id, "on:change": (e) => onChange(e.target.value) }),
            h("datalist", { id }, options.map((o) => h("option", { value: o.value }, o.label)))
          )
        );
      }
      return label(
        h(
          "select",
          { "on:change": (e) => onChange(e.target.value) },
          options.map((o) => h("option", { value: o.value, selected: o.value === value }, o.label))
        )
      );
    }
    if (selector.action || selector.object) {
      return label(
        h("textarea", {
          rows: 6,
          value: JSON.stringify(value ?? null, null, 2),
          "on:change": (e) => {
            try {
              onChange(JSON.parse(e.target.value));
              e.target.classList.remove("bad");
            } catch (_err) {
              e.target.classList.add("bad");
            }
          },
        })
      );
    }
    if (selector.number) {
      return label(h("input", { type: "number", value: value ?? "", "on:change": (e) => onChange(Number(e.target.value)) }));
    }
    return label(h("input", { value: value ?? "", "on:input": (e) => onChange(e.target.value) }));
  }

  _text(value, onChange, label, extra = {}) {
    return this._sel({ text: {} }, value ?? "", (v) => onChange(v ?? ""), { label, ...extra });
  }

  _select(options, value, onChange, opts = {}) {
    const list = options.map(([v, l]) => ({ value: v, label: l }));
    if (value !== undefined && value !== "" && !list.some((o) => o.value === value)) {
      list.push({ value, label: String(value) });
    }
    return this._sel(
      { select: { options: list, mode: "dropdown", custom_value: !!opts.custom, sort: false } },
      value,
      onChange,
      { required: !opts.custom, ...opts }
    );
  }

  _button(label, onClick, { primary = false, danger = false, disabled = false } = {}) {
    if (defined("ha-button")) {
      return h(
        "ha-button",
        {
          disabled,
          "@appearance": primary ? "accent" : "plain",
          "@variant": danger ? "danger" : "brand",
          "@unelevated": primary,
          "on:click": (ev) => {
            ev.stopPropagation();
            if (!disabled) onClick();
          },
        },
        label
      );
    }
    return h(
      "button",
      { class: `btn ${primary ? "primary" : ""} ${danger ? "danger" : ""}`, disabled, "on:click": onClick },
      label
    );
  }

  _iconButton(icon, label, onClick, disabled = false) {
    if (defined("ha-icon-button")) {
      return h(
        "ha-icon-button",
        { label, disabled, "@title": label, "on:click": (ev) => (ev.stopPropagation(), !disabled && onClick()) },
        h("ha-icon", { icon })
      );
    }
    return h("button", { class: "btn icon", title: label, disabled, "on:click": onClick }, label);
  }

  _panelBox(header, content, { expanded = false, secondary } = {}) {
    if (defined("ha-expansion-panel")) {
      return h("ha-expansion-panel", { header, secondary, expanded, "@outlined": true }, h("div", { class: "pad" }, content));
    }
    return h("details", { open: expanded, class: "details" }, h("summary", {}, header), h("div", { class: "pad" }, content));
  }

  _card(header, content, cls = "") {
    return h("ha-card", { header, class: cls }, h("div", { class: "card-content" }, content));
  }

  // ---- action editor -----------------------------------------------------------------------
  /**
   * Editor for one action. `get()` reads the current action from the model, `set(a)` writes it
   * (undefined = remove). Unknown fields of the action are preserved on field edits.
   */
  _actionEditor(get, set, { gesture = "tap", allowUnset = true, decorated = false, hint = true, voice = false } = {}) {
    const box = h("div", { class: "action" });
    const draw = () => {
      const cur = get();
      const type = isObj(cur) ? cur.type : "";
      const UNSET = "__unset__";
      // Voice is offered on keys only (an existing voice action elsewhere still shows).
      const types = ACTION_TYPES.filter(([t]) => t !== "voice" || voice || type === "voice");
      const options = [...(allowUnset ? [[UNSET, "Not set"]] : []), ...types];
      const fields = [];
      fields.push(
        this._select(options, type || (allowUnset ? UNSET : ""), (v) => {
          if (v === UNSET) v = "";
          if ((v ?? "") === (get()?.type ?? "")) return;
          if (!v) {
            set(undefined);
          } else {
            const old = isObj(get()) ? get() : {};
            const next = { type: v };
            if (decorated) for (const f of ["label", "icon"]) if (f in old) next[f] = old[f];
            if (v === "tv_key") {
              next.key = "";
              if (gesture === "hold") next.hold = "passthrough";
            } else if (v === "page") next.page = this._pages[0]?.id || "next";
            else if (v === "app") next.cmd = "settings";
            else if (v === "ha") next.action = "";
            else if (v === "voice") next.target = "ha";
            else if (v === "choose") next.entity = "";
            set(next);
          }
          draw();
        }, { label: "Action" })
      );
      const patch = (changes) => {
        const next = { ...(get() || {}), ...changes };
        for (const [k, v] of Object.entries(changes)) if (v === undefined) delete next[k];
        set(next);
      };
      if (type === "tv_key") {
        fields.push(
          this._select(
            this._tvKeys.map((k) => [k, k]),
            cur.key ?? "",
            (v) => patch({ key: String(v ?? "").trim() }),
            { label: "TV key", custom: true, helper: "Pick one or type any key name" }
          )
        );
        if (gesture === "hold") {
          fields.push(
            this._select(TV_HOLD_MODES, cur.hold ?? "passthrough", (v) => patch({ hold: v || undefined }), {
              label: "Hold mode",
            })
          );
        }
      } else if (type === "ha") {
        fields.push(
          this._sel({ action: {} }, toSelectorAction(cur), (v) => {
            const { action, extra } = fromSelectorAction(v, get());
            set(action);
            warn.hidden = !extra;
          })
        );
        const warn = h("div", { class: "hint warn", hidden: true }, "Only the first action is used.");
        fields.push(warn);
        if (gesture === "hold") {
          fields.push(
            h(
              "div",
              { class: "switch-row" },
              h("span", {}, "Repeat while held"),
              this._sel({ boolean: {} }, !!cur.repeat, (v) => patch({ repeat: v ? true : undefined }))
            )
          );
        }
      } else if (type === "page") {
        const pages = this._pages.filter(isObj).map((p) => [p.id, `${p.title || p.id}`]);
        fields.push(
          this._select([...pages, ["next", "Next page"], ["prev", "Previous page"]], cur.page ?? "", (v) => patch({ page: v }), {
            label: "Page",
          })
        );
      } else if (type === "event") {
        if (hint) {
          fields.push(
            h(
              "div",
              { class: "hint" },
              "Use in automations. Every key also fires device triggers (and the astrion_remote_button event) whatever it is mapped to."
            )
          );
        }
      } else if (type === "app") {
        fields.push(this._select(APP_CMDS, cur.cmd ?? "settings", (v) => patch({ cmd: v }), { label: "Command" }));
      } else if (type === "choose") {
        fields.push(
          this._sel({ entity: { filter: { domain: CHOOSE_DOMAINS } } }, cur.entity ?? "", (v) => patch({ entity: v || "" }), {
            label: "List (select / input_select)",
            required: true,
          })
        );
        fields.push(this._text(cur.title, (v) => patch({ title: v || undefined }), "Chooser title (optional)"));
        if (hint) {
          fields.push(h("div", { class: "hint" }, "Opens a list of the entity's options on the remote; picking one selects it."));
        }
      } else if (type === "voice") {
        fields.push(this._select(VOICE_TARGETS, cur.target ?? "ha", (v) => {
            patch({ target: v || "ha" });
            draw();
          }, { label: "Assistant" }));
        if (hint) {
          fields.push(
            h(
              "div",
              { class: "hint" },
              cur.target === "tv"
                ? "Talks to Google Assistant on the TV while the key is held."
                : "Runs Home Assistant Assist with the remote's microphone. Pick the assistant on the Astrion Remote device page."
            )
          );
        }
      }
      box.replaceChildren(...fields);
    };
    draw();
    return box;
  }

  _gestureEditors(keyId, ctx) {
    return GESTURES.map(([g, label]) =>
      h(
        "div",
        { class: "gesture" },
        h("div", { class: "gesture-title" }, label),
        this._actionEditor(
          () => this._gestureTarget(keyId, ctx, false)?.[g],
          (a) => this._setGesture(keyId, ctx, g, a),
          { gesture: g, voice: true }
        )
      )
    );
  }

  // ---- shell -------------------------------------------------------------------------------
  _renderShell() {
    this.shadowRoot.replaceChildren(
      h("style", {}, STYLE),
      (this._toolbar = h("div", { class: "toolbar" })),
      (this._tabsEl = h("div", { class: "tabs" })),
      h(
        "div",
        { class: "content" },
        (this._errorsEl = h("div", { class: "errors" })),
        (this._bodyEl = h("div", { class: "body" }))
      ),
      (this._footerEl = h("div", { class: "footer" }))
    );
  }

  _renderAll() {
    try {
      this._renderToolbar();
      this._renderTabs();
      this._renderErrors();
      this._renderBody();
      this._renderFooter();
    } catch (err) {
      this._showCrash(err);
    }
  }

  _showCrash(err) {
    // eslint-disable-next-line no-console
    console.error("Astrion panel render error", err);
    this._bodyEl.replaceChildren(
      this._card("Something went wrong", [
        h("p", {}, String(err?.message || err)),
        h("p", { class: "hint" }, "Your config was not changed. Use the YAML tab or the integration's options as a fallback."),
      ])
    );
  }

  _renderToolbar() {
    const items = [];
    if (defined("ha-menu-button")) items.push(h("ha-menu-button", { hass: this._hass, narrow: this._narrow }));
    items.push(h("div", { class: "title" }, "Astrion Remote"));
    if (this._entries.length > 1) {
      items.push(
        h(
          "select",
          {
            class: "entry-pick",
            "on:change": (e) => {
              if (this._dirty && !confirm("Discard unsaved changes?")) {
                e.target.value = this._entryId;
                return;
              }
              this._load(e.target.value);
            },
          },
          this._entries.map((e) => h("option", { value: e.entry_id, selected: e.entry_id === this._entryId }, e.title))
        )
      );
    }
    this._toolbar.replaceChildren(...items);
  }

  _renderTabs() {
    const tabs = [
      ["buttons", "Buttons"],
      ["pages", "Pages"],
      ["yaml", "YAML"],
    ];
    this._tabsEl.replaceChildren(
      ...tabs.map(([id, label]) =>
        h(
          "button",
          {
            class: `tab ${this._tab === id ? "active" : ""}`,
            disabled: this._status !== "ready",
            "on:click": () => {
              this._tab = id;
              this._renderTabs();
              this._renderBody();
            },
          },
          label
        )
      )
    );
  }

  _pathText(path) {
    const p = arr(path);
    if (p[0] === "keys" && p[1]) {
      const rest = p.slice(2).map((x) => (x === "contexts" ? "app" : x));
      return [this._keyLabel(p[1]), ...rest].join(" › ");
    }
    if (p[0] === "pages" && typeof p[1] === "number") {
      const page = this._pages[p[1]];
      const rest = [];
      for (let i = 2; i < p.length; i++) {
        if (p[i] === "sections" && typeof p[i + 1] === "number") {
          rest.push(`section ${p[i + 1] + 1}`);
          i++;
        } else if ((p[i] === "items" || p[i] === "buttons") && typeof p[i + 1] === "number") {
          rest.push(`${p[i] === "items" ? "item" : "button"} ${p[i + 1] + 1}`);
          i++;
        } else rest.push(p[i]);
      }
      return [`Page "${page?.title || page?.id || p[1] + 1}"`, ...rest].join(" › ");
    }
    return p.join(" › ") || "Config";
  }

  _renderErrors() {
    if (!this._errorsEl) return;
    if (!this._errors.length || this._status !== "ready") {
      this._errorsEl.replaceChildren();
      return;
    }
    this._errorsEl.replaceChildren(
      h(
        "div",
        { class: "error-box" },
        h("b", {}, `${this._errors.length} problem${this._errors.length > 1 ? "s" : ""} to fix before saving`),
        h(
          "ul",
          {},
          this._errors.slice(0, 12).map((e) => h("li", {}, h("span", { class: "path" }, this._pathText(e.path)), ": ", e.msg))
        )
      )
    );
  }

  _markErrors() {
    if (this._tab === "buttons") this._renderChips();
    if (this._tab === "pages") {
      this._renderPageList();
      for (const el of this.shadowRoot.querySelectorAll("[data-path]")) {
        el.classList.toggle("has-error", this._errorsAt(JSON.parse(el.dataset.path)).length > 0);
      }
    }
  }

  _renderFooter() {
    if (!this._footerEl) return;
    const ready = this._status === "ready";
    const dirty = this._dirty;
    let text = "";
    if (ready) {
      if (this._saving) text = "Saving…";
      else if (this._stale) text = h("span", { class: "stale" }, "Changed elsewhere: Reload");
      else if (dirty) text = "Unsaved changes";
      else text = this._message || "All changes saved";
    }
    this._footerEl.classList.toggle("dirty", dirty);
    this._footerEl.replaceChildren(
      h("div", { class: "footer-text" }, text, this._errors.length && dirty ? h("span", { class: "err-count" }, ` · ${this._errors.length} problem(s)`) : null),
      ready && this._stale ? this._button("Reload", () => this._reloadStale(), { disabled: !!this._saving }) : null,
      this._button("Revert", () => this._revert(), { disabled: !dirty || !!this._saving }),
      this._button("Save", () => this._save(), { primary: true, disabled: !dirty || !!this._saving })
    );
  }

  _renderBody() {
    if (!this._bodyEl) return;
    try {
      if (this._status === "loading") {
        this._bodyEl.replaceChildren(h("div", { class: "center" }, "Loading…"));
      } else if (this._status === "empty") {
        this._bodyEl.replaceChildren(
          this._card("No remote configured", "Add the Astrion Remote integration under Settings → Devices & services first.")
        );
      } else if (this._status === "error") {
        this._bodyEl.replaceChildren(this._card("Could not load the remote config", h("p", {}, this._message)));
      } else if (this._tab === "buttons") this._renderButtons();
      else if (this._tab === "pages") this._renderPages();
      else this._renderYaml();
    } catch (err) {
      this._showCrash(err);
    }
  }

  // ---- Buttons tab -------------------------------------------------------------------------
  _renderButtons() {
    this._chipsEl = h("div", { class: "remote" });
    this._keyEditorEl = h("div", { class: "key-editor" });
    this._bodyEl.replaceChildren(
      this._resetBar(
        "keys",
        "Reset buttons to default",
        "Replace your button mappings with the current default mappings? You can undo this once.",
        "Buttons reset to default and published"
      ),
      h("div", { class: "buttons-layout" }, h("div", { class: "remote-wrap" }, this._chipsEl), this._keyEditorEl)
    );
    this._renderChips();
    this._renderKeyEditor();
  }

  _chip(id) {
    const key = this._keyObj(id, false) || {};
    const color = KEY_COLORS[id];
    const icon = KEY_ICONS[id];
    const ctxCount = isObj(key.contexts) ? Object.keys(key.contexts).length : 0;
    const badges = [];
    if (isObj(key.double)) badges.push("2×");
    if (isObj(key.hold)) badges.push("hold");
    if (ctxCount) badges.push(`${ctxCount} app${ctxCount > 1 ? "s" : ""}`);
    const errs = this._errorsAt(["keys", id]).length;
    return h(
      "button",
      {
        class: `chip ${id === this._selKey ? "selected" : ""} ${color ? "colour" : ""} ${errs ? "has-error" : ""} k-${id}`,
        style: color ? `--key-colour:${color}` : undefined,
        title: this._keyLabel(id),
        "on:click": () => {
          this._selKey = id;
          this._renderChips();
          this._renderKeyEditor();
        },
      },
      h(
        "div",
        { class: "chip-label" },
        icon && defined("ha-icon") ? h("ha-icon", { icon }) : null,
        h("span", {}, this._keyLabel(id))
      ),
      h("div", { class: "chip-sum" }, this._summary(key.tap)),
      badges.length ? h("div", { class: "chip-badges" }, badges.join(" · ")) : null
    );
  }

  _renderChips() {
    if (!this._chipsEl || this._tab !== "buttons") return;
    const known = new Set(this._keys.map((k) => k.id));
    const placed = new Set();
    const rows = LAYOUT.map(([cls, ids]) => {
      const present = ids.filter((id) => !known.size || known.has(id));
      present.forEach((id) => placed.add(id));
      if (cls === "dpad") {
        return h("div", { class: "row dpad" }, present.map((id) => h("div", { class: `cell c-${id}` }, this._chip(id))));
      }
      return h("div", { class: `row ${cls}` }, present.map((id) => this._chip(id)));
    });
    const extra = this._keys.map((k) => k.id).filter((id) => !placed.has(id));
    if (extra.length) rows.push(h("div", { class: "row row4" }, extra.map((id) => this._chip(id))));
    this._chipsEl.replaceChildren(...rows);
  }

  _renderKeyEditor() {
    if (!this._keyEditorEl) return;
    const id = this._selKey;
    const key = this._keyObj(id, false) || {};
    const contexts = isObj(key.contexts) ? Object.keys(key.contexts) : [];
    const available = this._contexts.filter((c) => !contexts.includes(c));

    const overrides = contexts.map((ctx) => {
      const ctxActions = key.contexts[ctx] || {};
      const parts = GESTURES.filter(([g]) => isObj(ctxActions[g])).map(([g, l]) => `${l}: ${this._summary(ctxActions[g])}`);
      return this._panelBox(
        ctx,
        [
          ...this._gestureEditors(id, ctx),
          h(
            "div",
            { class: "actions-row" },
            this._button(
              "Remove override",
              () => {
                if (!confirm(`Remove the override for "${ctx}"?`)) return;
                const k = this._keyObj(id, false);
                if (k && isObj(k.contexts)) {
                  delete k.contexts[ctx];
                  if (!Object.keys(k.contexts).length) delete k.contexts;
                  if (!Object.keys(k).length) delete this._config.keys[id];
                }
                this._touched({ chips: true });
                this._renderKeyEditor();
              },
              { danger: true }
            )
          ),
        ],
        { secondary: parts.join(" · ") || "Falls back to the default mapping" }
      );
    });

    const addRow = h(
      "div",
      { class: "add-row" },
      this._select(available.map((c) => [c, c]), this._newCtx || undefined, (v) => (this._newCtx = String(v ?? "").trim()), {
        label: "App / context value",
        custom: true,
        helper: "Pick a recent value of the TV context entity or type one",
      }),
      this._button("Add override", () => {
        const ctx = (this._newCtx || "").trim();
        if (!ctx) return;
        const k = this._keyObj(id, true);
        if (!isObj(k.contexts)) k.contexts = {};
        if (!isObj(k.contexts[ctx])) k.contexts[ctx] = {};
        this._newCtx = "";
        this._touched({ chips: true });
        this._renderKeyEditor();
      })
    );

    const ctxEntity = this._config?.tv?.context_entity;
    this._keyEditorEl.replaceChildren(
      this._card(
        `${this._keyLabel(id)} key`,
        [h("div", { class: "gestures" }, this._gestureEditors(id, null)), this._warnSlot(["keys", id])],
        "editor-card"
      ),
      this._card(
        "Per-app overrides",
        [
          h(
            "p",
            { class: "hint" },
            ctxEntity
              ? `Used instead of the default when ${ctxEntity} has this value. Gestures left "Not set" fall back to the default.`
              : "Set tv.context_entity (YAML tab or integration options) to use per-app overrides."
          ),
          ...overrides,
          addRow,
        ],
        "editor-card"
      )
    );
  }

  // ---- Pages tab ---------------------------------------------------------------------------
  _renderPages() {
    const pages = this._pages;
    if (this._selPage >= pages.length) this._selPage = Math.max(0, pages.length - 1);
    this._pageListEl = h("div", { class: "page-list" });
    this._pageDetailEl = h("div", { class: "page-detail" });
    this._bodyEl.replaceChildren(
      this._resetBar(
        "pages",
        "Reset pages to default",
        "Replace your pages with the current default layout? You can undo this once.",
        "Pages reset to default and published"
      ),
      h("div", { class: "pages-layout" }, this._pageListEl, this._pageDetailEl)
    );
    this._renderPageList();
    this._renderPageDetail();
  }

  _movePage(i, d) {
    const pages = this._pages;
    const j = i + d;
    if (j < 0 || j >= pages.length) return;
    [pages[i], pages[j]] = [pages[j], pages[i]];
    if (this._selPage === i) this._selPage = j;
    else if (this._selPage === j) this._selPage = i;
    this._touched();
    this._renderPages();
  }

  _pageRefs(id) {
    let n = 0;
    const visit = (a) => {
      if (isObj(a) && a.type === "page" && a.page === id) n++;
    };
    for (const key of Object.values(isObj(this._config.keys) ? this._config.keys : {})) {
      if (!isObj(key)) continue;
      GESTURES.forEach(([g]) => visit(key[g]));
      for (const c of Object.values(isObj(key.contexts) ? key.contexts : {})) if (isObj(c)) GESTURES.forEach(([g]) => visit(c[g]));
    }
    for (const p of this._pages) {
      for (const s of arr(p?.sections)) {
        arr(s?.buttons).forEach(visit);
        visit(s?.action);
        arr(s?.items).forEach((it) => visit(it?.action));
      }
    }
    return n;
  }

  _renderPageList() {
    if (!this._pageListEl || this._tab !== "pages") return;
    const pages = this._pages;
    const rows = pages.map((p, i) =>
      h(
        "div",
        {
          class: `page-row ${i === this._selPage ? "selected" : ""} ${this._errorsAt(["pages", i]).length ? "has-error" : ""}`,
          "on:click": () => {
            this._selPage = i;
            this._renderPageList();
            this._renderPageDetail();
          },
        },
        h("div", { class: "page-name" }, h("div", {}, p?.title || p?.id || "(untitled)"), h("div", { class: "sub" }, `${p?.id ?? ""} · ${arr(p?.sections).length} sections`)),
        this._iconButton("mdi:arrow-up", "Move up", () => this._movePage(i, -1), i === 0),
        this._iconButton("mdi:arrow-down", "Move down", () => this._movePage(i, 1), i === pages.length - 1),
        this._iconButton(
          "mdi:delete-outline",
          "Delete page",
          () => {
            const refs = this._pageRefs(p?.id);
            const warn = refs ? ` ${refs} action(s) point to it and must be changed before saving.` : "";
            if (!confirm(`Delete page "${p?.title || p?.id}"?${warn}`)) return;
            pages.splice(i, 1);
            this._touched();
            this._renderPages();
          },
          pages.length <= 1
        )
      )
    );
    const add = h(
      "div",
      { class: "add-row" },
      this._text(this._newPageTitle, (v) => (this._newPageTitle = v), "New page title"),
      this._button("Add page", () => {
        const title = (this._newPageTitle || "").trim() || "New page";
        const taken = new Set([...pages.map((p) => p?.id), "next", "prev"]);
        let id = slug(title);
        for (let n = 2; taken.has(id); n++) id = `${slug(title)}_${n}`;
        pages.push({ id, title, sections: [] });
        this._selPage = pages.length - 1;
        this._newPageTitle = "";
        this._touched();
        this._renderPages();
      })
    );
    this._pageListEl.replaceChildren(this._card("Pages", [...rows, add]));
  }

  _renderPageDetail() {
    const page = this._pages[this._selPage];
    if (!isObj(page)) {
      this._pageDetailEl.replaceChildren(this._card("No page", "Add a page to start."));
      return;
    }
    const pi = this._selPage;
    const head = this._card(
      `Page "${page.title || page.id}"`,
      [
        h(
          "div",
          { class: "grid2" },
          this._text(page.title, (v) => {
            page.title = v;
            this._touched({ pages: true });
          }, "Title"),
          this._sel({ icon: {} }, page.icon ?? "", (v) => {
            if (v) page.icon = v;
            else delete page.icon;
            this._touched();
          }, { label: "Icon (optional)" })
        ),
        h("div", { class: "hint" }, `Page id: ${page.id} (used by "Go to page" actions)`),
      ]
    );
    if (!Array.isArray(page.sections)) page.sections = page.sections ? arr(page.sections) : [];
    const sections = page.sections.map((s, si) => this._sectionCard(page, pi, s, si));
    const add = h(
      "div",
      { class: "add-row" },
      this._select(SECTION_TYPES, this._newSectionType, (v) => (this._newSectionType = v || "tiles"), { label: "Section type" }),
      this._button("Add section", () => {
        const type = this._newSectionType || "tiles";
        const section = { type };
        if (type === "tiles") Object.assign(section, { columns: 3, items: [] });
        if (type === "keys") section.items = [];
        if (type === "now_playing") section.buttons = [];
        page.sections.push(section);
        this._touched({ pages: true });
        this._renderPageDetail();
      })
    );
    this._pageDetailEl.replaceChildren(head, ...sections, this._card("Add a section", add));
    this._markErrors();
  }

  _sectionCard(page, pi, section, si) {
    const sections = page.sections;
    const redraw = () => {
      this._touched({ pages: true });
      this._renderPageDetail();
    };
    if (!isObj(section)) {
      return this._card(`Section ${si + 1}`, [
        h("p", {}, "This section is not a mapping; edit it in the YAML tab."),
        this._button("Delete section", () => (sections.splice(si, 1), redraw()), { danger: true }),
      ]);
    }
    const typeLabel = SECTION_TYPES.find(([t]) => t === section.type)?.[1] || section.type || "Unknown";
    const header = h(
      "div",
      { class: "section-head" },
      h("span", { class: "type-badge" }, typeLabel),
      isObj(section.visible_if) ? h("span", { class: "sub" }, this._visibleSummary(section.visible_if)) : null,
      h("div", { class: "grow" }),
      this._iconButton("mdi:arrow-up", "Move up", () => {
        [sections[si - 1], sections[si]] = [sections[si], sections[si - 1]];
        redraw();
      }, si === 0),
      this._iconButton("mdi:arrow-down", "Move down", () => {
        [sections[si + 1], sections[si]] = [sections[si], sections[si + 1]];
        redraw();
      }, si === sections.length - 1),
      this._iconButton("mdi:delete-outline", "Delete section", () => {
        if (!confirm(`Delete this ${typeLabel} section?`)) return;
        sections.splice(si, 1);
        redraw();
      })
    );
    const body = [
      this._text(section.title, (v) => {
        if (v) section.title = v;
        else delete section.title;
        this._touched();
      }, "Title (optional)"),
    ];
    const path = ["pages", pi, "sections", si];
    const entityField = (domains, required = true) =>
      this._sel(
        { entity: domains ? { filter: { domain: domains } } : {} },
        section.entity ?? "",
        (v) => {
          if (v) section.entity = v;
          else delete section.entity;
          this._touched();
        },
        { label: `Entity${domains ? ` (${domains.join(", ")})` : ""}`, required }
      );

    switch (section.type) {
      case "now_playing":
        body.push(entityField(SECTION_ENTITY_DOMAINS.now_playing));
        body.push(
          this._itemsEditor(section, "buttons", "Buttons", () => ({ type: "none", label: "" }), (item, idx, list) => [
            this._text(item.label, (v) => {
              if (v) list[idx].label = v;
              else delete list[idx].label;
              this._touched();
            }, "Label"),
            this._actionEditor(() => list[idx], (a) => {
              list[idx] = a === undefined ? { type: "none", ...(item.label ? { label: item.label } : {}) } : a;
              this._touched();
            }, { allowUnset: false, decorated: true, hint: false }),
          ], redraw, path)
        );
        break;
      case "tiles":
        body.push(
          this._sel({ number: { min: 1, max: 3, step: 1, mode: "box" } }, section.columns ?? 3, (v) => {
            const n = parseInt(v, 10);
            if (n >= 1 && n <= 3) section.columns = n;
            this._touched();
          }, { label: "Columns (1–3)" })
        );
        body.push(
          this._itemsEditor(section, "items", "Tiles", () => ({ label: "" }), (item, idx, list) => [
            h(
              "div",
              { class: "grid2" },
              this._text(item.label, (v) => ((list[idx].label = v), this._touched()), "Label"),
              this._text(item.sub, (v) => {
                if (v) list[idx].sub = v;
                else delete list[idx].sub;
                this._touched();
              }, "Sub text (optional)")
            ),
            this._sel({ entity: {} }, item.entity ?? "", (v) => {
              if (v) list[idx].entity = v;
              else delete list[idx].entity;
              this._touched();
            }, { label: "Entity (optional, shows its state)" }),
            this._actionEditor(() => list[idx].action, (a) => {
              if (a === undefined) delete list[idx].action;
              else list[idx].action = a;
              this._touched();
            }, { hint: false }),
          ], redraw, path)
        );
        break;
      case "segmented":
      case "slider":
      case "rocker":
      case "switch":
        body.push(entityField(SECTION_ENTITY_DOMAINS[section.type]));
        break;
      case "keys":
        body.push(
          this._itemsEditor(section, "items", "Keys", () => ({ label: "", action: { type: "none" } }), (item, idx, list) => [
            this._text(item.label, (v) => ((list[idx].label = v), this._touched()), "Label"),
            this._actionEditor(() => list[idx].action, (a) => {
              list[idx].action = a === undefined ? { type: "none" } : a;
              this._touched();
            }, { allowUnset: false, hint: false }),
          ], redraw, path)
        );
        break;
      default:
        body.push(h("p", { class: "hint" }, "Unknown section type; edit it in the YAML tab."));
    }
    body.push(this._visibleIfEditor(section, redraw));
    return h(
      "ha-card",
      { class: "section-card", "@data-path": JSON.stringify(path) },
      h("div", { class: "card-content" }, header, this._warnSlot(path), ...body)
    );
  }

  _visibleSummary(cond) {
    if (!isObj(cond) || !cond.entity) return "Always shown";
    const mode = Array.isArray(cond.state_in) ? "state_in" : "state_not";
    const states = arr(cond[mode]);
    const friendly = this._hass?.states?.[cond.entity]?.attributes?.friendly_name || cond.entity;
    const list = states.length ? states.join(", ") : "(no states)";
    return `Shown when ${friendly} ${mode === "state_in" ? "is" : "is not"} ${list}`;
  }

  /** "Show only when…": visible_if = {entity, state_not | state_in: [..]} (exactly one list). */
  _visibleIfEditor(section, redraw) {
    const cond = isObj(section.visible_if) ? section.visible_if : null;
    const mode = cond && Array.isArray(cond.state_in) ? "state_in" : "state_not";
    const content = [];
    if (!cond) {
      content.push(h("div", { class: "hint" }, "Always shown."));
      content.push(
        h("div", { class: "actions-row" }, this._button("Add condition", () => {
          section.visible_if = { entity: "", state_not: ["off", "idle", "unavailable", "standby"] };
          redraw();
        }))
      );
    } else {
      content.push(
        this._sel({ entity: {} }, cond.entity ?? "", (v) => {
          cond.entity = v || "";
          this._touched();
        }, { label: "Entity", required: true })
      );
      content.push(
        this._select(VISIBLE_MODES, mode, (v) => {
          if (!v || v === mode) return;
          const states = arr(cond[mode]);
          delete cond.state_not;
          delete cond.state_in;
          cond[v] = states;
          redraw();
        }, { label: "State" })
      );
      const options = [...new Set([...COMMON_STATES, ...arr(cond[mode])])].map((o) => ({ value: o, label: o }));
      content.push(
        this._sel({ select: { options, multiple: true, custom_value: true, mode: "dropdown" } }, arr(cond[mode]), (v) => {
          cond[mode] = arr(v).map(String).filter(Boolean);
          this._touched();
        }, { label: "States" })
      );
      content.push(
        h("div", { class: "actions-row" }, this._button("Remove condition", () => {
          delete section.visible_if;
          redraw();
        }, { danger: true }))
      );
    }
    return this._panelBox("Show only when…", content, {
      expanded: !!cond && !cond.entity,
      secondary: this._visibleSummary(cond),
    });
  }

  _itemsEditor(section, field, title, make, renderItem, redraw, path) {
    if (!Array.isArray(section[field])) section[field] = section[field] ? arr(section[field]) : [];
    const list = section[field];
    this._open = this._open || new Set();
    const rows = list.map((item, idx) => {
      if (!isObj(item)) list[idx] = item = { label: String(item ?? "") };
      const itemPath = [...path, field, idx];
      const openKey = JSON.stringify([this._selPage, ...itemPath.slice(2)]);
      const open = this._open.has(openKey) || this._errorsAt(itemPath).length > 0;
      const action = field === "buttons" ? item : item.action;
      const body = h("div", { class: "item-body", hidden: !open }, renderItem(item, idx, list));
      const chevron = this._iconButton(open ? "mdi:chevron-up" : "mdi:chevron-down", open ? "Collapse" : "Edit", () => {
        const now = body.hidden;
        body.hidden = !now;
        if (now) this._open.add(openKey);
        else this._open.delete(openKey);
        const icon = chevron.querySelector("ha-icon");
        if (icon) icon.icon = now ? "mdi:chevron-up" : "mdi:chevron-down";
      });
      return h(
        "div",
        { class: "item", "@data-path": JSON.stringify(itemPath) },
        h(
          "div",
          { class: "item-head" },
          chevron,
          h(
            "div",
            { class: "item-name" },
            h("div", {}, `${idx + 1}. ${item.label || "(no label)"}`),
            h("div", { class: "sub" }, [item.entity, isObj(action) ? this._summary(action) : null].filter(Boolean).join(" · "))
          ),
          h("div", { class: "grow" }),
          this._iconButton("mdi:arrow-up", "Move up", () => {
            [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]];
            redraw();
          }, idx === 0),
          this._iconButton("mdi:arrow-down", "Move down", () => {
            [list[idx + 1], list[idx]] = [list[idx], list[idx + 1]];
            redraw();
          }, idx === list.length - 1),
          this._iconButton("mdi:delete-outline", "Remove", () => {
            list.splice(idx, 1);
            redraw();
          })
        ),
        body
      );
    });
    return h(
      "div",
      { class: "items" },
      h("div", { class: "items-title" }, title),
      rows.length ? rows : h("div", { class: "hint" }, "None yet."),
      h("div", { class: "actions-row" }, this._button(`Add ${title.toLowerCase().replace(/s$/, "")}`, () => {
        list.push(make());
        this._open = this._open || new Set();
        this._open.add(JSON.stringify([this._selPage, ...path.slice(2), field, list.length - 1]));
        redraw();
      }))
    );
  }

  // ---- YAML tab ----------------------------------------------------------------------------
  // ---- Remote settings (YAML tab) ---------------------------------------------------------
  _renderRemoteSettings() {
    const current = this._config?.tv?.transport ?? "auto";
    const warn = h("div", { class: "hint warn", hidden: current !== "bluetooth" }, BLUETOOTH_WARNING);
    return this._card("Remote", [
      h(
        "p",
        { class: "hint" },
        "Key route: how TV keys reach the TV. The remote's own Settings → Key route overrides this; motion settings (wake on pickup, sleep when put down) are set on the remote."
      ),
      this._select(TV_TRANSPORTS, current, (v) => {
        const tv = { ...(this._config.tv || {}) };
        if (!v || v === "auto") delete tv.transport;
        else tv.transport = v;
        this._config = { ...this._config, tv };
        warn.hidden = v !== "bluetooth";
        this._touched();
        if (this._yamlPending === undefined) this._renderYaml(); // keep the YAML view in step
      }, { label: "Key route" }),
      warn,
    ]);
  }

  _renderYaml() {
    const hasYaml = defined("ha-selector");
    const status = h("div", { class: "hint" });
    const editor = this._sel({ object: {} }, clone(this._config), (v) => {
      if (isObj(v)) {
        this._yamlPending = v;
        status.textContent = "Edited: press Apply to use it in the editor.";
      }
    });
    this._bodyEl.replaceChildren(
      this._renderRemoteSettings(),
      this._card(hasYaml ? "Config as YAML" : "Config as JSON", [
        h(
          "p",
          { class: "hint" },
          "The full remote config for import/export. Apply copies it into the editor; Save validates and publishes it. The allowlist is computed on save."
        ),
        h("div", { class: "yaml" }, editor),
        status,
        h(
          "div",
          { class: "actions-row" },
          this._button("Apply", () => {
            if (!isObj(this._yamlPending)) {
              status.textContent = "Nothing to apply (or the text is not a valid mapping).";
              return;
            }
            this._config = clone(this._yamlPending);
            this._yamlPending = undefined;
            this._touched();
            this._renderYaml();
            this._validate(true);
          }, { primary: true }),
          this._button("Reset text", () => {
            this._yamlPending = undefined;
            this._renderYaml();
          })
        ),
      ])
    );
  }
}

const STYLE = `
:host {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--primary-background-color);
  color: var(--primary-text-color);
  font-family: var(--ha-font-family-body, Roboto, sans-serif);
}
.toolbar {
  display: flex; align-items: center; gap: 8px;
  height: var(--header-height, 56px); padding: 0 12px;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color));
  border-bottom: var(--app-header-border-bottom, none);
  position: sticky; top: 0; z-index: 3;
}
.toolbar .title { font-size: 20px; margin-left: 8px; flex: 1; }
.entry-pick { font: inherit; padding: 4px 8px; border-radius: 4px; }
.tabs {
  display: flex; gap: 4px; padding: 0 16px;
  background: var(--app-header-background-color, var(--primary-color));
  position: sticky; top: var(--header-height, 56px); z-index: 3;
}
.tab {
  background: none; border: none; cursor: pointer; font: inherit; font-weight: 500;
  color: var(--app-header-text-color, var(--text-primary-color)); opacity: .75;
  padding: 12px 16px; border-bottom: 2px solid transparent; text-transform: uppercase; letter-spacing: .05em; font-size: 14px;
}
.tab.active { opacity: 1; border-bottom-color: var(--app-header-text-color, var(--text-primary-color)); }
.tab:disabled { cursor: default; }
.content { flex: 1; padding: 16px; max-width: 1200px; width: 100%; box-sizing: border-box; margin: 0 auto; }
.center { padding: 48px; text-align: center; color: var(--secondary-text-color); }
ha-card { display: block; margin-bottom: 16px; }
ha-card:not(:defined) { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--divider-color); }
.card-content { padding: 0 16px 16px; }
ha-card:not([header]) .card-content, .section-card .card-content { padding-top: 12px; }
.hint { color: var(--secondary-text-color); font-size: 13px; margin: 4px 0 8px; }
.hint.warn { color: var(--warning-color, #f57c00); }
.grow { flex: 1; }
.sub { color: var(--secondary-text-color); font-size: 12px; }
ha-selector { display: block; margin: 8px 0; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
:host([narrow]) .grid2 { grid-template-columns: 1fr; }
.add-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.add-row > ha-selector { flex: 1; min-width: 200px; }
.actions-row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
.switch-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.switch-row ha-selector { margin: 0; }
.error-box {
  border-left: 4px solid var(--error-color); background: var(--card-background-color);
  border-radius: 8px; padding: 8px 16px; margin-bottom: 16px; color: var(--primary-text-color);
}
.error-box ul { margin: 4px 0; padding-left: 18px; }
.error-box .path { font-weight: 500; color: var(--error-color); }
.has-error { outline: 2px solid var(--error-color); outline-offset: -2px; }
/* footer */
.footer {
  position: sticky; bottom: 0; z-index: 3; display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; background: var(--card-background-color); border-top: 1px solid var(--divider-color);
}
.footer-text { flex: 1; color: var(--secondary-text-color); }
.footer.dirty .footer-text { color: var(--primary-text-color); font-weight: 500; }
.err-count { color: var(--error-color); }
.stale { color: var(--warning-color); font-weight: 500; }
.warning-line { color: var(--warning-color); font-size: 0.85em; margin: 4px 0; }
/* buttons tab */
.buttons-layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; align-items: start; }
:host([narrow]) .buttons-layout, .narrow-layout { grid-template-columns: 1fr; }
@media (max-width: 900px) { .buttons-layout, .pages-layout { grid-template-columns: 1fr !important; } }
.remote-wrap { position: sticky; top: 120px; }
.remote {
  background: var(--card-background-color); border: 1px solid var(--divider-color);
  border-radius: 40px; padding: 20px 16px; display: flex; flex-direction: column; gap: 12px;
}
.row { display: grid; gap: 8px; }
.row1 { grid-template-columns: minmax(0, 120px); justify-content: center; }
.row2 { grid-template-columns: repeat(2, minmax(0, 120px)); justify-content: center; }
.row3 { grid-template-columns: repeat(3, 1fr); }
.row4 { grid-template-columns: repeat(4, 1fr); }
.dpad {
  grid-template-columns: repeat(3, 1fr);
  grid-template-areas: ". up ." "left ok right" ". down .";
  background: var(--secondary-background-color, rgba(127,127,127,.08)); border-radius: 50%; padding: 12px; aspect-ratio: 1;
  align-items: center; max-width: 300px; margin: 0 auto; width: 100%; box-sizing: border-box;
}
.c-up { grid-area: up; } .c-down { grid-area: down; } .c-left { grid-area: left; } .c-right { grid-area: right; } .c-ok { grid-area: ok; }
.c-ok .chip { border-radius: 50%; aspect-ratio: 1; justify-content: center; }
.chip {
  display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 0; width: 100%;
  font: inherit; cursor: pointer; color: var(--primary-text-color); text-align: center;
  background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 12px; padding: 6px 4px;
}
.chip:hover { border-color: var(--primary-color); }
.chip.selected { border-color: var(--primary-color); box-shadow: 0 0 0 2px var(--primary-color) inset; }
.chip.colour {
  background: color-mix(in srgb, var(--key-colour) 22%, var(--card-background-color));
  border-top: 4px solid var(--key-colour);
}
.chip-label { display: flex; align-items: center; gap: 4px; font-weight: 500; font-size: 13px; }
.chip-label ha-icon { --mdc-icon-size: 18px; }
.chip-sum, .chip-badges { font-size: 11px; color: var(--secondary-text-color); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-badges { color: var(--primary-color); }
.gestures { display: grid; gap: 4px; }
.gesture { border-top: 1px solid var(--divider-color); padding-top: 8px; }
.gesture:first-child { border-top: none; padding-top: 0; }
.gesture-title { font-weight: 500; margin-bottom: 2px; }
ha-expansion-panel, .details { display: block; margin: 8px 0; }
.pad { padding: 0 8px 8px; }
.details { border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px; }
/* pages tab */
.pages-layout { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
.page-row {
  display: flex; align-items: center; gap: 2px; padding: 4px 4px 4px 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid transparent;
}
.page-row:hover { background: var(--secondary-background-color, rgba(127,127,127,.08)); }
.page-row.selected { border-color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
.page-name { flex: 1; min-width: 0; }
.section-head { display: flex; align-items: center; gap: 4px; }
.type-badge { background: var(--primary-color); color: var(--text-primary-color, #fff); border-radius: 12px; padding: 2px 10px; font-size: 12px; font-weight: 500; }
.items { margin-top: 8px; border-top: 1px solid var(--divider-color); padding-top: 8px; }
.items-title { font-weight: 500; }
.item { border: 1px solid var(--divider-color); border-radius: 8px; padding: 4px 12px 8px; margin: 8px 0; }
.item-head { display: flex; align-items: center; gap: 4px; }
.item-name { min-width: 0; }
.item-name .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item { padding: 4px 8px; }
.item-body { padding: 0 4px 4px; }
.yaml { min-height: 200px; }
/* fallbacks (HA form elements not loaded) */
.fallback { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; font-size: 13px; color: var(--secondary-text-color); }
.fallback input, .fallback select, .fallback textarea {
  font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
  border: 1px solid var(--divider-color); border-radius: 4px; padding: 8px;
}
.fallback textarea { font-family: var(--code-font-family, monospace); min-height: 120px; }
.fallback textarea.bad { border-color: var(--error-color); }
.btn {
  font: inherit; cursor: pointer; border-radius: 18px; padding: 6px 14px; border: 1px solid var(--divider-color);
  background: none; color: var(--primary-color);
}
.btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
.btn.danger { color: var(--error-color); }
.btn:disabled { opacity: .5; cursor: default; }
.tab-head { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 8px; }
`;

if (!customElements.get("astrion-remote-panel")) {
  customElements.define("astrion-remote-panel", AstrionRemotePanel);
}

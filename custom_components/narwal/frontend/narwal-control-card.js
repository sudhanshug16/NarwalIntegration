/*
 * Narwal Control Card
 *
 * This bundled, dependency-free Lovelace card talks only to the integration's
 * Home Assistant services.  It never opens a robot WebSocket from the browser.
 */

const CARD_TYPE = "narwal-control-card";
const DRIVE_DURATION_MS = 100;
const DRIVE_GAP_MS = 30;

const MODE_VALUES = {
  Vacuum: "vacuum",
  Mop: "mop",
  "Vacuum then mop": "vacuum_then_mop",
  "Vacuum and mop": "vacuum_and_mop",
};

const SUCTION_VALUES = {
  AI: "ai",
  Quiet: "quiet",
  Standard: "standard",
  Strong: "strong",
  "Super powerful": "super_powerful",
  "Ultra powerful": "ultra_powerful",
};

const WATER_VALUES = { Dry: "dry", Normal: "normal", Wet: "wet" };
const SCRUB_VALUES = { Normal: "normal", High: "high" };
const ROUTE_VALUES = { Standard: "standard", Meticulous: "meticulous" };

class NarwalControlCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.vacuum_entity || !config.map_entity) {
      throw new Error("Set both vacuum_entity and map_entity for narwal-control-card.");
    }
    this._config = config;
    this._selectedRooms = new Set();
    this._pendingPoint = null;
    this._lastRevision = null;
    this._drive = null;
    this._driveToken = 0;
    this._imageFrame = null;
    this._loadedFrame = null;
    this._message = "Choose a point or mapped rooms when the robot is idle.";
    this._renderShell();
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 10;
  }

  connectedCallback() {
    if (!this._onWindowBlur) {
      this._onWindowBlur = () => this._releaseDrive();
      this._onVisibilityChange = () => {
        if (document.visibilityState !== "visible") this._releaseDrive();
      };
    }
    window.addEventListener("blur", this._onWindowBlur);
    document.addEventListener("visibilitychange", this._onVisibilityChange);
  }

  disconnectedCallback() {
    window.removeEventListener("blur", this._onWindowBlur);
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    this._releaseDrive();
  }

  _renderShell() {
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
    else this.attachShadow({ mode: "open" });

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }
        .header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 16px 10px; }
        .title { font-size: 1.2rem; font-weight: 600; }
        .state { color: var(--secondary-text-color); font-size: .92rem; text-transform: capitalize; }
        .content { padding: 0 16px 16px; }
        .map-stage { position: relative; width: 100%; min-height: 180px; border-radius: 12px; overflow: hidden; background: var(--secondary-background-color); touch-action: none; }
        .map-stage.disabled { opacity: .72; }
        .map-image { width: 100%; height: auto; display: block; user-select: none; -webkit-user-drag: none; }
        .map-placeholder { display: grid; min-height: 180px; place-items: center; padding: 18px; color: var(--secondary-text-color); text-align: center; }
        .map-placeholder[hidden] { display: none; }
        .room-layer { position: absolute; inset: 0; pointer-events: none; }
        .room-marker { position: absolute; transform: translate(-50%, -50%); pointer-events: auto; max-width: 42%; border: 1px solid rgba(255,255,255,.8); border-radius: 999px; padding: 3px 7px; color: #fff; background: rgba(20,20,20,.64); font: inherit; font-size: .76rem; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-shadow: 0 1px 2px #000; }
        .room-marker.selected { background: var(--primary-color); border-color: var(--primary-color); }
        .destination { position: absolute; width: 23px; height: 23px; transform: translate(-50%, -50%); border-radius: 50% 50% 50% 0; rotate: -45deg; background: var(--error-color, #db4437); box-shadow: 0 1px 5px rgba(0,0,0,.6); pointer-events: none; }
        .destination::after { content: ""; position: absolute; width: 7px; height: 7px; border-radius: 50%; background: #fff; top: 8px; left: 8px; }
        .caption { margin: 9px 0 12px; color: var(--secondary-text-color); font-size: .88rem; line-height: 1.35; }
        .actions, .room-actions, .settings { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        button { appearance: none; border: 0; border-radius: 8px; min-height: 36px; padding: 0 12px; cursor: pointer; color: var(--primary-text-color); background: var(--secondary-background-color); font: inherit; }
        button[disabled] { cursor: not-allowed; opacity: .52; }
        button.primary { color: var(--text-primary-color, #fff); background: var(--primary-color); }
        button.danger { color: #fff; background: var(--error-color, #db4437); }
        button.compact { min-height: 30px; padding: 0 9px; font-size: .84rem; }
        .section { margin-top: 16px; }
        .section-title { margin-bottom: 8px; font-weight: 600; }
        .room-chip { border: 1px solid var(--divider-color); background: transparent; }
        .room-chip.selected { border-color: var(--primary-color); color: var(--text-primary-color, #fff); background: var(--primary-color); }
        .empty { color: var(--secondary-text-color); font-size: .9rem; }
        .joystick-row { display: grid; grid-template-columns: 52px 52px 52px; gap: 7px; justify-content: center; }
        .joystick-row + .joystick-row { margin-top: 7px; }
        .joystick { min-width: 0; width: 52px; padding: 0; font-size: 1.3rem; font-weight: 700; touch-action: none; user-select: none; }
        .stop-row { display: flex; justify-content: center; margin-top: 10px; }
        .safety { margin-top: 10px; padding: 10px; border-radius: 8px; color: var(--secondary-text-color); background: var(--secondary-background-color); font-size: .84rem; line-height: 1.35; }
        .notice { min-height: 1.2em; margin-top: 10px; font-size: .9rem; color: var(--secondary-text-color); }
        .notice.error { color: var(--error-color, #db4437); }
        .settings { color: var(--secondary-text-color); font-size: .84rem; }
        .setting { padding: 4px 8px; border-radius: 999px; background: var(--secondary-background-color); }
        .custom-zone { margin-top: 10px; padding: 10px; border: 1px dashed var(--divider-color); border-radius: 8px; color: var(--secondary-text-color); font-size: .84rem; line-height: 1.35; }
        @media (max-width: 450px) { .content { padding-left: 12px; padding-right: 12px; } .header { padding-left: 12px; padding-right: 12px; } }
      </style>
      <ha-card>
        <div class="header">
          <div class="title">${this._escapeText(this._config.title || "Narwal control")}</div>
          <div class="state" id="state"></div>
        </div>
        <div class="content">
          <div class="map-stage" id="map-stage">
            <img class="map-image" id="map-image" alt="Narwal map" hidden />
            <div class="map-placeholder" id="map-placeholder">Waiting for the Narwal map…</div>
            <div class="room-layer" id="room-layer"></div>
            <div class="destination" id="destination" hidden></div>
          </div>
          <div class="caption" id="map-caption"></div>
          <div class="actions">
            <button class="primary" id="go-button" disabled>Go to selected point</button>
            <button id="clear-point" disabled>Clear point</button>
            <button id="stop-navigation">Stop navigation</button>
          </div>

          <div class="section">
            <div class="section-title">Mapped rooms</div>
            <div class="room-actions" id="room-actions"></div>
            <div class="custom-zone">Custom rectangle cleaning is intentionally disabled: the AX15 local protocol for arbitrary zones has not been verified. Select mapped rooms instead.</div>
            <div class="settings" id="settings"></div>
            <div class="room-actions" style="margin-top: 9px;">
              <button class="primary" id="clean-rooms" disabled>Clean selected rooms</button>
              <button id="clear-rooms" disabled>Clear rooms</button>
            </div>
          </div>

          <div class="section">
            <div class="section-title">Hold-to-drive joystick</div>
            <div class="joystick-row"><span></span><button class="joystick" data-linear="8" data-angular="0" aria-label="Drive forward">↑</button><span></span></div>
            <div class="joystick-row"><button class="joystick" data-linear="0" data-angular="8" aria-label="Turn left">↶</button><span></span><button class="joystick" data-linear="0" data-angular="-8" aria-label="Turn right">↷</button></div>
            <div class="joystick-row"><span></span><button class="joystick" data-linear="-8" data-angular="0" aria-label="Drive backward">↓</button><span></span></div>
            <div class="stop-row"><button class="danger" id="emergency-stop">Emergency stop</button></div>
            <div class="safety" id="safety"></div>
          </div>
          <div class="notice" id="notice" role="status"></div>
        </div>
      </ha-card>
    `;

    this._els = {
      state: this.shadowRoot.getElementById("state"),
      mapStage: this.shadowRoot.getElementById("map-stage"),
      mapImage: this.shadowRoot.getElementById("map-image"),
      mapPlaceholder: this.shadowRoot.getElementById("map-placeholder"),
      roomLayer: this.shadowRoot.getElementById("room-layer"),
      destination: this.shadowRoot.getElementById("destination"),
      mapCaption: this.shadowRoot.getElementById("map-caption"),
      goButton: this.shadowRoot.getElementById("go-button"),
      clearPoint: this.shadowRoot.getElementById("clear-point"),
      stopNavigation: this.shadowRoot.getElementById("stop-navigation"),
      roomActions: this.shadowRoot.getElementById("room-actions"),
      settings: this.shadowRoot.getElementById("settings"),
      cleanRooms: this.shadowRoot.getElementById("clean-rooms"),
      clearRooms: this.shadowRoot.getElementById("clear-rooms"),
      emergencyStop: this.shadowRoot.getElementById("emergency-stop"),
      safety: this.shadowRoot.getElementById("safety"),
      notice: this.shadowRoot.getElementById("notice"),
    };

    this._els.mapStage.addEventListener("click", (event) => this._pickPoint(event));
    this._els.goButton.addEventListener("click", () => this._goToPoint());
    this._els.clearPoint.addEventListener("click", () => {
      this._pendingPoint = null;
      this._setMessage("Destination cleared.");
      this._update();
    });
    this._els.stopNavigation.addEventListener("click", () => this._stopNavigation());
    this._els.cleanRooms.addEventListener("click", () => this._cleanSelectedRooms());
    this._els.clearRooms.addEventListener("click", () => {
      this._selectedRooms.clear();
      this._update();
    });
    this._els.emergencyStop.addEventListener("click", () => this._emergencyStop());
    this._els.mapImage.addEventListener("load", () => {
      this._loadedFrame = this._els.mapImage.dataset.frame || null;
      this._update();
    });
    this._els.mapImage.addEventListener("error", () => {
      this._loadedFrame = null;
      this._setMessage("The map image could not be loaded. Check the camera entity.", true);
      this._update();
    });

    this.shadowRoot.querySelectorAll(".joystick").forEach((button) => {
      const linear = Number(button.dataset.linear);
      const angular = Number(button.dataset.angular);
      button.addEventListener("pointerdown", (event) => this._startDrive(event, linear, angular));
      button.addEventListener("pointerup", () => this._releaseDrive());
      button.addEventListener("pointercancel", () => this._releaseDrive());
      button.addEventListener("lostpointercapture", () => this._releaseDrive());
      button.addEventListener("contextmenu", (event) => event.preventDefault());
    });
  }

  _state(entityId) {
    return this._hass?.states?.[entityId];
  }

  _frame(camera) {
    const attributes = camera?.attributes || {};
    const revision = attributes.navigation_map_revision;
    const count = attributes.render_count;
    return revision && Number.isFinite(Number(count)) ? `${revision}:${count}` : null;
  }

  _busy(camera, vacuum) {
    const attributes = camera?.attributes || {};
    return !["idle", "docked"].includes(vacuum?.state) || Boolean(attributes.manual_control_active) || Boolean(attributes.point_navigation_active);
  }

  _canGoTo(camera, vacuum) {
    return Boolean(this._frame(camera)) && this._loadedFrame === this._frame(camera) && !this._busy(camera, vacuum) && !this._drive;
  }

  _canDrive(camera, vacuum) {
    const attributes = camera?.attributes || {};
    return vacuum?.state === "idle" && !Boolean(attributes.manual_control_active) && !Boolean(attributes.point_navigation_active) && !this._drive;
  }

  _canClean(camera, vacuum) {
    return !this._busy(camera, vacuum) && !this._drive;
  }

  _getValue(name, fallback) {
    const entityId = this._config?.[`${name}_entity`];
    return this._state(entityId)?.state || fallback;
  }

  _cleaningData() {
    const routeState = this._getValue("route", null);
    const data = {
      entity_id: this._config.vacuum_entity,
      rooms: [...this._selectedRooms].sort((a, b) => a - b),
      mode: MODE_VALUES[this._getValue("mode", "Vacuum and mop")] || "vacuum_and_mop",
      suction: SUCTION_VALUES[this._getValue("suction", "Standard")] || "standard",
      water: WATER_VALUES[this._getValue("water", "Normal")] || "normal",
      mop_strength: SCRUB_VALUES[this._getValue("scrub", "Normal")] || "normal",
      passes: Math.min(3, Math.max(1, Number.parseInt(this._getValue("passes", "1"), 10) || 1)),
    };
    if (ROUTE_VALUES[routeState]) data.route = ROUTE_VALUES[routeState];
    return data;
  }

  _mapImageUrl(camera, frame) {
    const entityPicture = camera?.attributes?.entity_picture;
    let url = entityPicture || `/api/camera_proxy/${this._config.map_entity}`;
    if (!/^https?:/i.test(url) && typeof this._hass?.hassUrl === "function") url = this._hass.hassUrl(url);
    const separator = url.includes("?") ? "&" : "?";
    return `${url}${separator}narwal_frame=${encodeURIComponent(frame)}`;
  }

  _markers(camera) {
    const markers = camera?.attributes?.room_markers;
    if (!Array.isArray(markers)) return [];
    return markers.filter((marker) => Number.isInteger(marker?.id) && marker.id > 0 && typeof marker.name === "string" && Number.isFinite(marker.x) && Number.isFinite(marker.y) && marker.x >= 0 && marker.x < 1 && marker.y >= 0 && marker.y < 1);
  }

  _update() {
    if (!this._config || !this._els) return;
    const camera = this._state(this._config.map_entity);
    const vacuum = this._state(this._config.vacuum_entity);
    const frame = this._frame(camera);
    const revision = camera?.attributes?.navigation_map_revision || null;
    const mapReady = Boolean(frame && this._loadedFrame === frame);

    if (this._lastRevision && revision !== this._lastRevision) {
      this._pendingPoint = null;
      this._selectedRooms.clear();
    }
    this._lastRevision = revision;

    this._els.state.textContent = vacuum?.state || "unavailable";
    this._els.mapStage.classList.toggle("disabled", !mapReady);
    this._els.mapPlaceholder.hidden = Boolean(camera);
    this._els.mapImage.hidden = !camera;

    if (camera && frame && this._imageFrame !== frame) {
      this._imageFrame = frame;
      this._loadedFrame = null;
      this._els.mapImage.dataset.frame = frame;
      this._els.mapImage.src = this._mapImageUrl(camera, frame);
    }

    const canGo = this._canGoTo(camera, vacuum);
    const canDrive = this._canDrive(camera, vacuum);
    const canClean = this._canClean(camera, vacuum);
    const roomMarkers = this._markers(camera);
    const knownRoomIds = new Set(roomMarkers.map((marker) => marker.id));
    [...this._selectedRooms].forEach((id) => {
      if (!knownRoomIds.has(id)) this._selectedRooms.delete(id);
    });

    this._els.mapCaption.textContent = !camera
      ? "Map camera is unavailable."
      : !frame
        ? "Waiting for a rendered, revision-locked map frame."
        : !mapReady
          ? "Loading the current map frame before it can be used for navigation."
          : canGo
            ? "Tap a clear-looking map location, then explicitly confirm Go to selected point."
            : "Map actions are disabled while the robot is busy, under manual control, or navigating.";

    this._els.goButton.disabled = !this._pendingPoint || !canGo || this._pendingPoint.frame !== frame;
    this._els.clearPoint.disabled = !this._pendingPoint;
    // Stop paths remain available even when a stale camera update says there
    // is no task.  The integration treats them as safe, bypassing actions.
    this._els.stopNavigation.disabled = !this._hass?.callService;
    this._els.cleanRooms.disabled = this._selectedRooms.size === 0 || !canClean;
    this._els.clearRooms.disabled = this._selectedRooms.size === 0;
    this.shadowRoot.querySelectorAll(".joystick").forEach((button) => {
      // Do not disable a pressed control mid-gesture: some browsers then
      // suppress pointerup.  A second pointerdown is still ignored by
      // _startDrive while an existing bounded drive loop owns the control.
      button.disabled = !canDrive && !this._drive;
    });
    this._els.safety.textContent = canDrive
      ? "Hold an arrow to send 100 ms bounded pulses. Releasing, losing pointer capture, changing tabs, or blurring the window sends an immediate emergency telecontrol stop."
      : "Joystick is available only when the vacuum is idle, undocked, and not already doing a manual or point-navigation task. The integration performs a second server-side safety check.";

    this._renderDestination(frame);
    this._renderRooms(roomMarkers);
    this._renderSettings();
    this._els.notice.textContent = this._message || "";
    this._els.notice.classList.toggle("error", Boolean(this._messageIsError));
  }

  _renderDestination(frame) {
    const point = this._pendingPoint;
    const visible = Boolean(point && point.frame === frame);
    this._els.destination.hidden = !visible;
    if (visible) {
      this._els.destination.style.left = `${point.x * 100}%`;
      this._els.destination.style.top = `${point.y * 100}%`;
    }
  }

  _renderRooms(markers) {
    this._els.roomLayer.replaceChildren();
    this._els.roomActions.replaceChildren();
    if (!markers.length) {
      const empty = document.createElement("span");
      empty.className = "empty";
      empty.textContent = "No mapped rooms are available on this rendered map yet.";
      this._els.roomActions.append(empty);
      return;
    }
    for (const marker of markers) {
      const makeToggle = (className) => {
        const button = document.createElement("button");
        button.className = className;
        button.textContent = marker.name;
        button.classList.toggle("selected", this._selectedRooms.has(marker.id));
        const areaCells = Number.isFinite(marker.area_cells) ? marker.area_cells : 0;
        button.title = `${marker.name} (${areaCells.toLocaleString()} map cells)`;
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          if (this._selectedRooms.has(marker.id)) this._selectedRooms.delete(marker.id);
          else this._selectedRooms.add(marker.id);
          this._update();
        });
        return button;
      };
      const markerButton = makeToggle("room-marker");
      markerButton.style.left = `${marker.x * 100}%`;
      markerButton.style.top = `${marker.y * 100}%`;
      this._els.roomLayer.append(markerButton);
      this._els.roomActions.append(makeToggle("room-chip compact"));
    }
  }

  _renderSettings() {
    const labels = [
      ["Mode", this._getValue("mode", "Vacuum and mop")],
      ["Suction", this._getValue("suction", "Standard")],
      ["Water", this._getValue("water", "Normal")],
      ["Scrub", this._getValue("scrub", "Normal")],
      ["Passes", this._getValue("passes", "1")],
    ];
    const route = this._getValue("route", null);
    if (route) labels.push(["Route", route]);
    this._els.settings.replaceChildren();
    for (const [label, value] of labels) {
      const item = document.createElement("span");
      item.className = "setting";
      item.textContent = `${label}: ${value}`;
      this._els.settings.append(item);
    }
  }

  _pickPoint(event) {
    const camera = this._state(this._config.map_entity);
    const vacuum = this._state(this._config.vacuum_entity);
    const frame = this._frame(camera);
    if (!this._canGoTo(camera, vacuum) || !frame) return;
    const rect = this._els.mapImage.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.min(0.999999, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(0.999999, Math.max(0, (event.clientY - rect.top) / rect.height));
    this._pendingPoint = { x, y, frame, revision: camera.attributes.navigation_map_revision };
    this._setMessage("Destination selected. Confirm Go to selected point to send it to the robot.");
    this._update();
  }

  async _goToPoint() {
    const camera = this._state(this._config.map_entity);
    const vacuum = this._state(this._config.vacuum_entity);
    const point = this._pendingPoint;
    if (!point || !this._canGoTo(camera, vacuum) || point.frame !== this._frame(camera)) {
      this._setMessage("The selected map frame is no longer current. Choose the point again.", true);
      this._update();
      return;
    }
    const success = await this._callService("go_to", {
      entity_id: this._config.vacuum_entity,
      x: point.x,
      y: point.y,
      map_revision: point.revision,
    });
    if (success) {
      this._setMessage("Point navigation requested. Use Stop navigation or Emergency stop if needed.");
      this._pendingPoint = null;
    }
    this._update();
  }

  async _cleanSelectedRooms() {
    const camera = this._state(this._config.map_entity);
    const vacuum = this._state(this._config.vacuum_entity);
    if (!this._selectedRooms.size || !this._canClean(camera, vacuum)) return;
    const success = await this._callService("clean_rooms", this._cleaningData());
    if (success) this._setMessage("Mapped room cleaning requested.");
    this._update();
  }

  async _stopNavigation() {
    const success = await this._callService("stop_navigation", { entity_id: this._config.vacuum_entity });
    if (success) this._setMessage("Point navigation stop requested.");
    this._update();
  }

  async _emergencyStop() {
    this._drive = null;
    const success = await this._callService("stop_telecontrol", { entity_id: this._config.vacuum_entity }, { silent: true });
    this._setMessage(success ? "Emergency telecontrol stop requested." : "Emergency stop request failed; verify the robot immediately.", !success);
    this._update();
  }

  _startDrive(event, linearVelocity, angularVelocity) {
    const camera = this._state(this._config.map_entity);
    const vacuum = this._state(this._config.vacuum_entity);
    if (!this._canDrive(camera, vacuum)) return;
    event.preventDefault();
    const button = event.currentTarget;
    try {
      button.setPointerCapture(event.pointerId);
    } catch (_) {
      // A capture failure is harmless: pointercancel/window blur still stop it.
    }
    const drive = { token: ++this._driveToken, linearVelocity, angularVelocity };
    this._drive = drive;
    this._setMessage("Driving while held. Release to stop.");
    this._update();
    this._driveLoop(drive);
  }

  async _driveLoop(drive) {
    while (this._drive === drive) {
      const success = await this._callService("drive", {
        entity_id: this._config.vacuum_entity,
        linear_velocity: drive.linearVelocity,
        angular_velocity: drive.angularVelocity,
        duration_ms: DRIVE_DURATION_MS,
      }, { silent: true });
      if (!success || this._drive !== drive) {
        await this._releaseDrive();
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, DRIVE_GAP_MS));
    }
  }

  async _releaseDrive() {
    const drive = this._drive;
    if (!drive) return;
    this._drive = null;
    const success = await this._callService("stop_telecontrol", { entity_id: this._config?.vacuum_entity }, { silent: true });
    if (!success) this._setMessage("Could not confirm the joystick stop. Verify the robot immediately.", true);
    else this._setMessage("Joystick stopped.");
    this._update();
  }

  async _callService(service, data, options = {}) {
    if (!this._hass?.callService) {
      this._setMessage("Home Assistant is not connected to this card.", true);
      return false;
    }
    try {
      await this._hass.callService("narwal", service, data);
      return true;
    } catch (error) {
      if (!options.silent) this._setMessage(error?.message || `${service} was rejected by Home Assistant.`, true);
      return false;
    }
  }

  _setMessage(message, isError = false) {
    this._message = message;
    this._messageIsError = isError;
  }

  _escapeText(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }
}

if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, NarwalControlCard);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: `custom:${CARD_TYPE}`,
    name: "Narwal Control",
    description: "Map navigation, mapped-room cleaning, and bounded dead-man joystick controls for Narwal.",
  });
}

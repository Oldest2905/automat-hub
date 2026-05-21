/**
 * obd-gatt.js
 * The Automat Hub — Web Bluetooth GATT Bridge
 *
 * Handles real ELM327 OBD-II dongle communication via Web Bluetooth API.
 * Supports all common ELM327 clones (cheap Chinese dongles and premium ones).
 *
 * HOW ELM327 BLUETOOTH WORKS:
 *   The dongle exposes a BLE serial port (SPP over BLE).
 *   We write AT commands as text, read back raw OBD responses.
 *   All communication is text over a notify/write characteristic.
 *
 * TESTED WITH:
 *   - Generic ELM327 V2.1 Bluetooth (most common in Nigeria markets)
 *   - Veepeak OBDCheck BLE+
 *   - FIXD Sensor
 *   - OBD Link MX+
 */

// ── KNOWN ELM327 SERVICE / CHARACTERISTIC UUIDs ──────────────
// Different clones use different UUIDs. We try all of them.
const ELM327_PROFILES = [
    {
        name: "Generic ELM327 BLE (most common cheap clone)",
        service: "0000fff0-0000-1000-8000-00805f9b34fb",
        notify: "0000fff1-0000-1000-8000-00805f9b34fb",
        write: "0000fff2-0000-1000-8000-00805f9b34fb",
    },
    {
        name: "ELM327 V2.1 / V1.5 BLE clone (alternate UUID)",
        service: "0000ffe0-0000-1000-8000-00805f9b34fb",
        notify: "0000ffe1-0000-1000-8000-00805f9b34fb",
        write: "0000ffe1-0000-1000-8000-00805f9b34fb", // same UUID for read/write
    },
    {
        name: "Veepeak OBDCheck BLE+",
        service: "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
        notify: "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
        write: "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
    },
    {
        name: "OBDLink MX+ BLE",
        service: "00001101-0000-1000-8000-00805f9b34fb",
        notify: "00001101-0000-1000-8000-00805f9b34fb",
        write: "00001101-0000-1000-8000-00805f9b34fb",
    },
];

// ── AT COMMANDS ───────────────────────────────────────────────
// ELM327 command set. Send as text, receive text response.
const AT_COMMANDS = {
    reset: "ATZ",        // Reset device
    echo_off: "ATE0",       // Turn off echo (cleaner responses)
    linefeed_off: "ATL0",       // Turn off linefeeds
    spaces_off: "ATS0",       // Remove spaces from responses
    header_off: "ATH0",       // Remove headers
    auto_protocol: "ATSP0",      // Auto-detect OBD protocol
    get_voltage: "ATRV",       // Battery voltage (e.g. "12.8V")
    get_rpm: "010C",       // Mode 01 PID 0C — Engine RPM
    get_speed: "010D",       // Mode 01 PID 0D — Vehicle speed
    get_coolant: "0105",       // Mode 01 PID 05 — Coolant temp
    get_fuel: "012F",       // Mode 01 PID 2F — Fuel level
    get_oil_temp: "015C",       // Mode 01 PID 5C — Oil temp
    get_throttle: "0111",       // Mode 01 PID 11 — Throttle position
    get_intake: "010F",       // Mode 01 PID 0F — Intake air temp
    get_odo: "01A6",       // Mode 01 PID A6 — Odometer (not all cars)
    get_dtc_count: "0101",       // Mode 01 PID 01 — DTC count + MIL status
    get_dtcs: "03",         // Mode 03 — Get stored DTCs
    get_pending: "07",         // Mode 07 — Get pending DTCs
    clear_dtcs: "04",         // Mode 04 — Clear DTCs (use with care)
    get_vin: "0902",       // Mode 09 PID 02 — VIN number
};

// ── RESPONSE DECODERS ─────────────────────────────────────────
function decodeRPM(raw) {
    // Response: "41 0C XX XX" — formula: ((A*256)+B)/4
    const bytes = parseOBDResponse(raw, "410C");
    if (!bytes) return null;
    return ((bytes[0] * 256) + bytes[1]) / 4;
}

function decodeSpeed(raw) {
    // Response: "41 0D XX" — value in km/h directly
    const bytes = parseOBDResponse(raw, "410D");
    return bytes ? bytes[0] : null;
}

function decodeCoolant(raw) {
    // Response: "41 05 XX" — formula: A - 40
    const bytes = parseOBDResponse(raw, "4105");
    return bytes ? bytes[0] - 40 : null;
}

function decodeFuel(raw) {
    // Response: "41 2F XX" — formula: (A/255)*100
    const bytes = parseOBDResponse(raw, "412F");
    return bytes ? Math.round((bytes[0] / 255) * 100) : null;
}

function decodeOilTemp(raw) {
    // Response: "41 5C XX" — formula: A - 40
    const bytes = parseOBDResponse(raw, "415C");
    return bytes ? bytes[0] - 40 : null;
}

function decodeThrottle(raw) {
    const bytes = parseOBDResponse(raw, "4111");
    return bytes ? Math.round((bytes[0] / 255) * 100) : null;
}

function decodeOdometer(raw) {
    // Response: "41 A6 XX XX XX XX" — formula: ((A*2^24)+(B*2^16)+(C*2^8)+D)/10
    const bytes = parseOBDResponse(raw, "41A6");
    if (!bytes || bytes.length < 4) return null;
    return Math.round(
        ((bytes[0] * 16777216) + (bytes[1] * 65536) + (bytes[2] * 256) + bytes[3]) / 10
    );
}

function decodeBattery(rawStr) {
    // ATRV returns e.g. "12.8V" — strip the V and parse
    const match = rawStr.replace(/\s/g, '').match(/(\d+\.?\d*)V/i);
    return match ? parseFloat(match[1]) : null;
}

function decodeDTCs(raw) {
    // Mode 03 returns hex pairs representing DTC codes
    // Each DTC is 2 bytes. First nibble is DTC type:
    // 0=P0, 1=P1, 2=P2, 3=P3, 4=C0, 8=B0, C=U0
    const clean = raw.replace(/[\s\r\n>]/g, '').replace(/43/g, '');
    const codes = [];
    for (let i = 0; i < clean.length - 3; i += 4) {
        const chunk = clean.slice(i, i + 4);
        if (chunk === '0000') continue;
        const first = parseInt(chunk[0], 16);
        const type = ['P', 'P', 'P', 'P', 'C', 'C', 'C', 'C',
            'B', 'B', 'B', 'B', 'U', 'U', 'U', 'U'][first];
        const digit1 = first & 3;
        const rest = chunk.slice(1);
        codes.push(`${type}${digit1}${rest.toUpperCase()}`);
    }
    return codes;
}

function parseOBDResponse(raw, expectedHeader) {
    // Clean response and extract data bytes after the header
    const clean = raw.replace(/[\s\r\n>]/g, '').toUpperCase();
    const header = expectedHeader.replace(/\s/g, '').toUpperCase();
    const idx = clean.indexOf(header);
    if (idx === -1) return null;
    const dataStr = clean.slice(idx + header.length);
    const bytes = [];
    for (let i = 0; i < dataStr.length - 1; i += 2) {
        bytes.push(parseInt(dataStr.slice(i, i + 2), 16));
    }
    return bytes.length > 0 ? bytes : null;
}

// ── MAIN OBD GATT CLASS ───────────────────────────────────────
class OBDGATTBridge {
    constructor(callbacks) {
        this.device = null;
        this.server = null;
        this.characteristic = null;
        this.writeChar = null;
        this.profile = null;
        this.responseBuffer = '';
        this.pendingResolve = null;
        this.pendingReject = null;
        this.callbacks = callbacks || {};
        // callbacks: onStatus, onData, onFault, onError
    }

    // ── SCAN AND CONNECT ─────────────────────────────────────────
    async connect() {
        if (!navigator.bluetooth) {
            throw new Error(
                'Web Bluetooth not available. Use Chrome or Edge on desktop, ' +
                'or Chrome on Android. Safari and Firefox do not support Web Bluetooth.'
            );
        }

        this._onStatus('Scanning for OBD adapters...');

        // Build filter list from all known service UUIDs
        const serviceUUIDs = ELM327_PROFILES.map(p => p.service);

        try {
            this.device = await navigator.bluetooth.requestDevice({
                filters: [
                    { namePrefix: 'OBDII' },
                    { namePrefix: 'ELM327' },
                    { namePrefix: 'V-Link' },
                    { namePrefix: 'OBD' },
                    { namePrefix: 'ELM' },
                    { namePrefix: 'Vlink' },
                    { namePrefix: 'OBDLINK' },
                    { namePrefix: 'Veepeak' },
                    { namePrefix: 'FIXD' },
                    ...serviceUUIDs.map(uuid => ({ services: [uuid] }))
                ],
                optionalServices: serviceUUIDs
            });
        } catch (e) {
            if (e.name === 'NotFoundError') {
                throw new Error('No OBD adapter found. Make sure your dongle is plugged in and Bluetooth is on.');
            }
            throw e;
        }

        this._onStatus(`Found: ${this.device.name}. Connecting...`);
        this.device.addEventListener('gattserverdisconnected', () => this._onDisconnect());

        this.server = await this.device.gatt.connect();
        this._onStatus('Connected to GATT server. Discovering services...');

        // Try each profile until one works
        for (const profile of ELM327_PROFILES) {
            try {
                const service = await this.server.getPrimaryService(profile.service);
                const notifyChar = await service.getCharacteristic(profile.notify);
                const writeChar = profile.write === profile.notify
                    ? notifyChar
                    : await service.getCharacteristic(profile.write);

                // Set up notifications (incoming data from dongle)
                await notifyChar.startNotifications();
                notifyChar.addEventListener('characteristicvaluechanged', (e) => {
                    const chunk = new TextDecoder().decode(e.target.value);
                    this.responseBuffer += chunk;
                    // ELM327 signals end of response with '>'
                    if (this.responseBuffer.includes('>')) {
                        const response = this.responseBuffer.trim();
                        this.responseBuffer = '';
                        if (this.pendingResolve) {
                            this.pendingResolve(response);
                            this.pendingResolve = null;
                            this.pendingReject = null;
                        }
                    }
                });

                this.characteristic = notifyChar;
                this.writeChar = writeChar;
                this.profile = profile;
                this._onStatus(`Connected via ${profile.name}`);
                break;
            } catch (e) {
                // This profile didn't work, try next
                continue;
            }
        }

        if (!this.characteristic) {
            throw new Error(
                'Could not find OBD service. Your adapter may not be supported. ' +
                'Try a generic ELM327 V2.1 Bluetooth adapter.'
            );
        }

        // Initialise ELM327
        await this._initELM327();
        return this.device.name;
    }

    // ── SEND AT COMMAND ──────────────────────────────────────────
    async send(command, timeoutMs = 5000) {
        return new Promise((resolve, reject) => {
            this.pendingResolve = resolve;
            this.pendingReject = reject;
            const data = new TextEncoder().encode(command + '\r');
            this.writeChar.writeValue(data).catch(reject);
            // Timeout fallback
            setTimeout(() => {
                if (this.pendingResolve) {
                    this.pendingResolve = null;
                    this.pendingReject = null;
                    resolve('TIMEOUT');
                }
            }, timeoutMs);
        });
    }

    // ── INIT ELM327 ──────────────────────────────────────────────
    async _initELM327() {
        this._onStatus('Initialising ELM327...');
        await this.send(AT_COMMANDS.reset, 3000);
        await this._sleep(1000); // ELM327 needs time after reset
        await this.send(AT_COMMANDS.echo_off);
        await this.send(AT_COMMANDS.linefeed_off);
        await this.send(AT_COMMANDS.spaces_off);
        await this.send(AT_COMMANDS.header_off);
        await this.send(AT_COMMANDS.auto_protocol);
        this._onStatus('ELM327 ready. Reading vehicle data...');
    }

    // ── READ ALL PIDs ─────────────────────────────────────────────
    async readAllData() {
        const data = {
            source: 'obd_hardware',
            adapter_id: this.device?.id,
            adapter_name: this.device?.name,
            timestamp: new Date().toISOString(),
            pids: {},
            dtcs: [],
            raw: {}
        };

        // Battery voltage (AT command, not PID)
        try {
            const raw = await this.send(AT_COMMANDS.get_voltage);
            data.raw.battery = raw;
            const val = decodeBattery(raw);
            if (val) {
                data.pids['0x42'] = val;
                data.battery_voltage = val;
                this._onData('battery_voltage', val, 'V');
            }
        } catch (e) { /* continue */ }

        // Engine RPM
        try {
            const raw = await this.send(AT_COMMANDS.get_rpm);
            data.raw.rpm = raw;
            const val = decodeRPM(raw);
            if (val !== null) {
                data.pids['0x0C'] = Math.round(val);
                data.engine_rpm = Math.round(val);
                this._onData('engine_rpm', Math.round(val), 'RPM');
            }
        } catch (e) { /* continue */ }

        // Vehicle speed
        try {
            const raw = await this.send(AT_COMMANDS.get_speed);
            data.raw.speed = raw;
            const val = decodeSpeed(raw);
            if (val !== null) {
                data.pids['0x0D'] = val;
                data.speed_kmh = val;
                this._onData('speed', val, 'km/h');
            }
        } catch (e) { /* continue */ }

        // Coolant temperature
        try {
            const raw = await this.send(AT_COMMANDS.get_coolant);
            data.raw.coolant = raw;
            const val = decodeCoolant(raw);
            if (val !== null) {
                data.pids['0x05'] = val;
                data.coolant_temp_c = val;
                this._onData('coolant_temp', val, '°C');
            }
        } catch (e) { /* continue */ }

        // Fuel level
        try {
            const raw = await this.send(AT_COMMANDS.get_fuel);
            data.raw.fuel = raw;
            const val = decodeFuel(raw);
            if (val !== null) {
                data.pids['0x2F'] = val;
                data.fuel_level_pct = val;
                this._onData('fuel_level', val, '%');
            }
        } catch (e) { /* continue */ }

        // Oil temperature
        try {
            const raw = await this.send(AT_COMMANDS.get_oil_temp);
            data.raw.oil = raw;
            const val = decodeOilTemp(raw);
            if (val !== null) {
                data.pids['0x5C'] = val;
                data.oil_temp_c = val;
                this._onData('oil_temp', val, '°C');
            }
        } catch (e) { /* continue */ }

        // Odometer
        try {
            const raw = await this.send(AT_COMMANDS.get_odo);
            data.raw.odometer = raw;
            const val = decodeOdometer(raw);
            if (val !== null) {
                data.pids['0xA6'] = val;
                data.odometer_km = val;
                this._onData('odometer', val, 'km');
            }
        } catch (e) { /* not all cars support this */ }

        // Fault codes (DTCs)
        try {
            const raw = await this.send(AT_COMMANDS.get_dtcs);
            data.raw.dtcs = raw;
            const codes = decodeDTCs(raw);
            data.dtcs = codes;
            data.fault_codes = codes;
            if (codes.length > 0) {
                this._onFault(codes);
            }
        } catch (e) { /* continue */ }

        // Pending DTCs
        try {
            const raw = await this.send(AT_COMMANDS.get_pending);
            const pending = decodeDTCs(raw);
            if (pending.length > 0) {
                data.dtcs = [...new Set([...data.dtcs, ...pending])];
                data.fault_codes = data.dtcs;
            }
        } catch (e) { /* continue */ }

        return data;
    }

    // ── GET LOCATION ──────────────────────────────────────────────
    async getLocation() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) { resolve(null); return; }
            navigator.geolocation.getCurrentPosition(
                pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
                () => resolve(null),
                { timeout: 5000, maximumAge: 30000 }
            );
        });
    }

    // ── DISCONNECT ─────────────────────────────────────────────────
    disconnect() {
        if (this.device?.gatt?.connected) {
            this.device.gatt.disconnect();
        }
    }

    _onDisconnect() {
        this._onStatus('Adapter disconnected.');
        if (this.callbacks.onDisconnect) this.callbacks.onDisconnect();
    }

    _onStatus(msg) {
        if (this.callbacks.onStatus) this.callbacks.onStatus(msg);
        else console.log('[OBD]', msg);
    }

    _onData(key, val, unit) {
        if (this.callbacks.onData) this.callbacks.onData(key, val, unit);
    }

    _onFault(codes) {
        if (this.callbacks.onFault) this.callbacks.onFault(codes);
        else console.warn('[OBD FAULTS]', codes);
    }

    _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}

// ── EXPORT ────────────────────────────────────────────────────
// Usage in connect-vehicle.html:
//
// const obd = new OBDGATTBridge({
//   onStatus: (msg) => updateStatusUI(msg),
//   onData:   (key, val, unit) => updatePIDDisplay(key, val, unit),
//   onFault:  (codes) => showFaultCodes(codes),
//   onDisconnect: () => resetUI()
// });
// await obd.connect();
// const data = await obd.readAllData();
// const location = await obd.getLocation();
// data.location = location;
// // Send to backend:
// await fetch('/fleet/scan/submit', {
//   method: 'POST',
//   headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
//   body: JSON.stringify({ vehicle_id: vehicleId, ...data })
// });

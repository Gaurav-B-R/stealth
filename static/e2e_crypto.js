/*
 * Rilono client-side end-to-end encryption (E2E) — WebCrypto, no dependencies.
 *
 * This is what makes "not even we can read your documents" true: key derivation and all
 * encryption/decryption happen in the browser. The server only ever receives opaque,
 * already-encrypted blobs and wrapped keys. The passphrase and the unwrapped master key
 * NEVER leave the browser.
 *
 * Design (envelope encryption):
 *   master key   : random 32 bytes, generated in-browser at setup.
 *   passphrase   : KEK_pass = PBKDF2-SHA256(passphrase, salt, 600k) -> AES-GCM-256.
 *                  wrapped_master_key = AESGCM(KEK_pass, master).
 *   recovery     : KEK_rec  = PBKDF2-SHA256(recovery_code, salt, 600k).
 *                  recovery_wrapped_master_key = AESGCM(KEK_rec, master).
 *   per file     : random DEK (32 bytes); blob = AESGCM(DEK, file);
 *                  wrapped_dek = AESGCM(master, DEK).
 * Every AES-GCM output is stored as IV(12 bytes) || ciphertext+tag.
 *
 * Works in the browser and in Node 18+ (WebCrypto global), so it can be unit-tested headless.
 */
(function (root) {
  'use strict';

  function getCrypto() {
    return root.crypto || (typeof globalThis !== 'undefined' && globalThis.crypto);
  }
  function getSubtle() {
    var c = getCrypto();
    return c && c.subtle;
  }

  var IV_BYTES = 12;
  var DEFAULT_ITER = 600000;
  var enc = new TextEncoder();

  function isSupported() {
    try {
      var c = getCrypto();
      return !!(c && c.subtle && c.getRandomValues);
    } catch (_) {
      return false;
    }
  }

  function randomBytes(n) {
    var b = new Uint8Array(n);
    getCrypto().getRandomValues(b);
    return b;
  }

  // ---- base64 <-> bytes (browser + Node) ----
  function bytesToB64(bytes) {
    var arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (typeof btoa === 'function') {
      var bin = '';
      for (var i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
      return btoa(bin);
    }
    return Buffer.from(arr).toString('base64');
  }
  function b64ToBytes(b64) {
    if (typeof atob === 'function') {
      var bin = atob(b64);
      var out = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    return new Uint8Array(Buffer.from(b64, 'base64'));
  }

  // ---- AES-GCM primitives (envelope = IV || ciphertext) ----
  function importAesKey(rawBytes, usages) {
    return getSubtle().importKey('raw', rawBytes, { name: 'AES-GCM' }, false, usages);
  }
  async function aesEncrypt(key, plaintextBytes) {
    var iv = randomBytes(IV_BYTES);
    var ct = new Uint8Array(await getSubtle().encrypt({ name: 'AES-GCM', iv: iv }, key, plaintextBytes));
    var out = new Uint8Array(iv.length + ct.length);
    out.set(iv, 0);
    out.set(ct, iv.length);
    return out;
  }
  async function aesDecrypt(key, envelopeBytes) {
    var bytes = envelopeBytes instanceof Uint8Array ? envelopeBytes : new Uint8Array(envelopeBytes);
    var iv = bytes.slice(0, IV_BYTES);
    var ct = bytes.slice(IV_BYTES);
    return new Uint8Array(await getSubtle().decrypt({ name: 'AES-GCM', iv: iv }, key, ct));
  }

  // ---- KDF ----
  function buildKdfString(saltB64, iterations) {
    return 'pbkdf2-sha256$' + (iterations || DEFAULT_ITER) + '$' + saltB64;
  }
  function parseKdfString(kdf) {
    var parts = String(kdf || '').split('$');
    if (parts.length !== 3) throw new Error('Bad kdf string');
    return { algo: parts[0], iterations: parseInt(parts[1], 10) || DEFAULT_ITER, saltB64: parts[2] };
  }
  async function deriveKEK(passphrase, saltB64, iterations) {
    var baseKey = await getSubtle().importKey(
      'raw', enc.encode(String(passphrase)), { name: 'PBKDF2' }, false, ['deriveKey']
    );
    return getSubtle().deriveKey(
      { name: 'PBKDF2', salt: b64ToBytes(saltB64), iterations: iterations || DEFAULT_ITER, hash: 'SHA-256' },
      baseKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt']
    );
  }

  // ---- recovery code (human-friendly, high entropy) ----
  // 20 chars from a 31-symbol alphabet (no I/O/0/1) ~= 99 bits; grouped 5-5-5-5.
  function generateRecoveryCode() {
    var alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    var bytes = randomBytes(20);
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += alphabet.charAt(bytes[i] % alphabet.length);
    return s.match(/.{1,5}/g).join('-');
  }
  function normalizeRecoveryCode(code) {
    return String(code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  }

  // ---- vault lifecycle (returns payloads for /api/e2e/*) ----
  async function createVault(passphrase) {
    var saltB64 = bytesToB64(randomBytes(16));
    var kdf = buildKdfString(saltB64, DEFAULT_ITER);
    var masterRaw = randomBytes(32);
    var passKek = await deriveKEK(passphrase, saltB64, DEFAULT_ITER);
    var wrapped_master_key = bytesToB64(await aesEncrypt(passKek, masterRaw));
    var recoveryCode = generateRecoveryCode();
    var recKek = await deriveKEK(normalizeRecoveryCode(recoveryCode), saltB64, DEFAULT_ITER);
    var recovery_wrapped_master_key = bytesToB64(await aesEncrypt(recKek, masterRaw));
    return {
      kdf: kdf,
      wrapped_master_key: wrapped_master_key,
      recovery_wrapped_master_key: recovery_wrapped_master_key,
      recoveryCode: recoveryCode,
      masterRaw: masterRaw
    };
  }

  async function unlockVault(vault, passphrase) {
    var p = parseKdfString(vault.kdf);
    var kek = await deriveKEK(passphrase, p.saltB64, p.iterations);
    try {
      return await aesDecrypt(kek, b64ToBytes(vault.wrapped_master_key));
    } catch (_) {
      throw new Error('Incorrect passphrase.');
    }
  }

  async function unlockWithRecovery(vault, recoveryCode) {
    var p = parseKdfString(vault.kdf);
    var kek = await deriveKEK(normalizeRecoveryCode(recoveryCode), p.saltB64, p.iterations);
    try {
      return await aesDecrypt(kek, b64ToBytes(vault.recovery_wrapped_master_key));
    } catch (_) {
      throw new Error('Incorrect recovery code.');
    }
  }

  // Re-wrap the SAME master key under a new passphrase (used by rotate + recover). Issues a
  // fresh recovery code as well, so the old one stops working after a reset.
  async function rewrapForNewPassphrase(masterRaw, newPassphrase) {
    var saltB64 = bytesToB64(randomBytes(16));
    var kdf = buildKdfString(saltB64, DEFAULT_ITER);
    var passKek = await deriveKEK(newPassphrase, saltB64, DEFAULT_ITER);
    var wrapped_master_key = bytesToB64(await aesEncrypt(passKek, masterRaw));
    var recoveryCode = generateRecoveryCode();
    var recKek = await deriveKEK(normalizeRecoveryCode(recoveryCode), saltB64, DEFAULT_ITER);
    var recovery_wrapped_master_key = bytesToB64(await aesEncrypt(recKek, masterRaw));
    return {
      kdf: kdf,
      wrapped_master_key: wrapped_master_key,
      recovery_wrapped_master_key: recovery_wrapped_master_key,
      recoveryCode: recoveryCode
    };
  }

  // ---- per-file encryption ----
  async function encryptBytes(plaintextBytes, masterRaw) {
    var dekRaw = randomBytes(32);
    var dekKey = await importAesKey(dekRaw, ['encrypt']);
    var blob = await aesEncrypt(dekKey, plaintextBytes);
    var masterKey = await importAesKey(masterRaw, ['encrypt']);
    var wrappedDekB64 = bytesToB64(await aesEncrypt(masterKey, dekRaw));
    return { blob: blob, wrappedDekB64: wrappedDekB64 };
  }

  async function encryptFile(file, masterRaw) {
    var buf = new Uint8Array(await file.arrayBuffer());
    return encryptBytes(buf, masterRaw);
  }

  async function decryptBlob(blobBytes, wrappedDekB64, masterRaw) {
    var masterKey = await importAesKey(masterRaw, ['decrypt']);
    var dekRaw = await aesDecrypt(masterKey, b64ToBytes(wrappedDekB64));
    var dekKey = await importAesKey(dekRaw, ['decrypt']);
    return aesDecrypt(dekKey, blobBytes);
  }

  var E2E = {
    isSupported: isSupported,
    randomSaltB64: function () { return bytesToB64(randomBytes(16)); },
    buildKdfString: buildKdfString,
    parseKdfString: parseKdfString,
    deriveKEK: deriveKEK,
    generateRecoveryCode: generateRecoveryCode,
    normalizeRecoveryCode: normalizeRecoveryCode,
    createVault: createVault,
    unlockVault: unlockVault,
    unlockWithRecovery: unlockWithRecovery,
    rewrapForNewPassphrase: rewrapForNewPassphrase,
    encryptBytes: encryptBytes,
    encryptFile: encryptFile,
    decryptBlob: decryptBlob,
    bytesToB64: bytesToB64,
    b64ToBytes: b64ToBytes
  };

  root.E2E = E2E;
  if (typeof module !== 'undefined' && module.exports) module.exports = E2E;
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : globalThis));

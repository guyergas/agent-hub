(() => {
  "use strict";

  const dbName = "agent-hub-private-vault:" + new URL(".", location.href).pathname;
  const utf8 = new TextEncoder();
  const decode = new TextDecoder();
  const initialState = {seq: 0, products: [], events: []};
  let unlockPromise;

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(dbName, 1);
      request.onupgradeneeded = () => request.result.createObjectStore("vault");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function readRecord(db) {
    return new Promise((resolve, reject) => {
      const request = db.transaction("vault").objectStore("vault").get("state");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function saveRecord(db, previous, record) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction("vault", "readwrite");
      const store = tx.objectStore("vault");
      const read = store.get("state");
      let saved = false;
      read.onsuccess = () => {
        if (read.result?.revision !== previous?.revision) return;
        store.put(record, "state");
        saved = true;
      };
      tx.oncomplete = () => resolve(saved);
      tx.onabort = () => reject(tx.error);
    });
  }

  async function derive(passphrase, salt) {
    const material = await crypto.subtle.importKey("raw", utf8.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({name:"PBKDF2",hash:"SHA-256",salt,iterations:600000},
      material,{name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
  }

  async function encrypt(state, key, salt, revision) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({name:"AES-GCM",iv},key,utf8.encode(JSON.stringify(state)));
    return {salt,iv,ciphertext,revision};
  }

  async function decrypt(record, key) {
    const plaintext = await crypto.subtle.decrypt({name:"AES-GCM",iv:record.iv},key,record.ciphertext);
    return JSON.parse(decode.decode(plaintext));
  }

  function askForKey(db, existing) {
    return new Promise(resolve => {
      const dialog = document.createElement("dialog");
      const heading = document.createElement("h2");
      heading.textContent = existing ? "פתיחת לוח הניהול" : "יצירת כספת ללוח הניהול";
      const description = document.createElement("p");
      description.textContent = "הנתונים נשמרים מוצפנים בדפדפן הזה. שמור את משפט הסיסמה במקום בטוח.";
      const form = document.createElement("form");
      const label = document.createElement("label");
      label.textContent = "משפט סיסמה";
      const input = document.createElement("input");
      input.type = "password";
      input.autocomplete = existing ? "current-password" : "new-password";
      input.required = true;
      input.minLength = 12;
      label.append(input);
      const submit = document.createElement("button");
      submit.textContent = existing ? "פתיחה" : "יצירה";
      submit.className = "primary";
      const status = document.createElement("p");
      status.setAttribute("role", "status");
      form.append(label, submit, status);
      dialog.append(heading,description,form);
      document.body.append(dialog);
      dialog.addEventListener("cancel", event => event.preventDefault());
      form.addEventListener("submit", async event => {
        event.preventDefault();
        if (submit.disabled) return;
        submit.disabled = true;
        status.textContent = "פותח את הלוח…";
        try {
          const record = await readRecord(db);
          const salt = record?.salt ?? crypto.getRandomValues(new Uint8Array(16));
          const key = await derive(input.value, salt);
          input.value = "";
          if (record) await decrypt(record,key);
          else if (!await saveRecord(db, undefined, await encrypt(initialState,key,salt,0))) {
            throw new Error("Vault changed during setup");
          }
          dialog.close();
          dialog.remove();
          resolve(key);
        } catch {
          status.textContent = "פתיחת הכספת נכשלה. בדוק את משפט הסיסמה או את זמינות האחסון בדפדפן.";
          input.focus();
        } finally {
          submit.disabled = false;
        }
      });
      dialog.showModal();
    });
  }

  async function initialize() {
    const db = await openDatabase();
    const key = await askForKey(db, await readRecord(db));
    const py = await loadPyodide({indexURL:new URL("./runtime/", location.href).href});
    const core = await fetch("./core.py");
    if (!core.ok) throw new Error("לא ניתן לטעון את לוגיקת הלוח");
    await py.runPythonAsync(await core.text());
    return {db,key,handle:py.globals.get("web_request")};
  }

  window.AgentHubPages = {
    async request(path, data) {
      unlockPromise ??= initialize();
      const {db,key,handle} = await unlockPromise;
      for(let attempt=0; attempt<3; attempt++){
        const record = await readRecord(db);
        const state = await decrypt(record,key);
        const result = JSON.parse(handle(path,JSON.stringify(data),JSON.stringify(state)));
        if(result.error) throw new Error(result.error);
        if(path!=="/change") return result.payload;
        const next = await encrypt(result.state,key,record.salt,record.revision+1);
        if(await saveRecord(db,record,next)) return result.payload;
      }
      throw new Error("הלוח השתנה בחלון אחר. נסה שוב.");
    }
  };
})();

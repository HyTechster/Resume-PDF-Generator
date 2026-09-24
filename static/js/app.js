// Draft save/restore, Markdown sample, add/remove entries, and live preview updates.
// Tabs are plain radio inputs styled in CSS, so they need no JS.
(() => {
  const KEY = "resume-pdf:draft";
  const read = () => {
    try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
  };
  const write = (data) => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch { /* private mode: no draft */ }
  };

  // Preview page: re-render as soon as a setting changes, and remember it for the form.
  // Focus goes back to the changed control after the reload, so keyboard users keep their place.
  const panel = document.querySelector("[data-autosubmit]");
  if (panel) {
    const update = panel.querySelector("[data-update]");
    update.hidden = true;
    try {
      const name = sessionStorage.getItem("resume-pdf:focus");
      sessionStorage.removeItem("resume-pdf:focus");
      if (name) panel.querySelector(`[name="${name}"]:checked`)?.focus();
    } catch { /* focus starts at the top instead */ }
    panel.addEventListener("change", (e) => {
      write({ ...read(), [e.target.name]: e.target.value });
      try { sessionStorage.setItem("resume-pdf:focus", e.target.name); } catch { /* ignore */ }
      update.click();
    });
  }

  const form = document.getElementById("resume-form");
  if (!form) return;

  const fields = () => [...form.elements].filter((el) => el.name && !["submit", "button"].includes(el.type));

  const addEntry = (key) => {
    const entry = document.getElementById(`entry-${key}`).content.firstElementChild.cloneNode(true);
    form.querySelector(`[data-entries="${key}"]`).append(entry);
    return entry;
  };

  // Repeated names (experience_title, ...) are saved as arrays, in page order.
  const saveDraft = () => {
    const data = {};
    for (const el of fields()) {
      if (el.type === "radio") { if (el.checked) data[el.name] = el.value; }
      else (data[el.name] ??= []).push(el.value);
    }
    write(data);
  };

  const restoreDraft = () => {
    const data = read();
    if (!data) return;
    for (const list of form.querySelectorAll("[data-entries]")) {
      const count = [].concat(data[list.dataset.count] ?? []).length;
      while (list.children.length < count) addEntry(list.dataset.entries);
    }
    const seen = {};
    for (const el of fields()) {
      if (!(el.name in data)) continue;
      const value = data[el.name];
      if (el.type === "radio") { el.checked = el.value === value; continue; }
      const i = (seen[el.name] = (seen[el.name] ?? -1) + 1);
      el.value = (Array.isArray(value) ? value[i] : value) ?? "";
    }
  };

  // After a server error the page already holds what was typed, so keep that instead.
  if (form.dataset.restoreDraft === "true") restoreDraft();

  let timer;
  form.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(saveDraft, 300);
  });
  form.addEventListener("change", saveDraft);
  form.addEventListener("submit", saveDraft);

  for (const button of form.querySelectorAll("[data-add]")) button.hidden = false;
  form.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    const remove = e.target.closest("[data-remove]");
    if (add) addEntry(add.dataset.add).querySelector("input, textarea").focus();
    if (remove) {
      const entry = remove.closest("[data-entry]");
      const list = entry.parentElement;
      if (list.children.length > 1) entry.remove();
      else entry.querySelectorAll("input, textarea").forEach((el) => (el.value = ""));
      form.querySelector(`[data-add="${list.dataset.entries}"]`).focus();
    }
    if (add || remove) saveDraft();
  });

  const sampleButton = form.querySelector("[data-load-sample]");
  const sample = document.getElementById("sample-md");
  const markdown = document.getElementById("f-markdown");
  sampleButton?.addEventListener("click", () => {
    if (markdown.value.trim() && !confirm("Replace what is in the Markdown box with the sample?")) return;
    markdown.value = sample.content.textContent.trim() + "\n";
    markdown.focus();
    saveDraft();
  });
})();

/* Monaco, mounted the same way by the student page and the Studio's Problem tab.
   One module because two copies of editor setup drift, and the theming is the
   fiddly part: Monaco brings its own colours and would otherwise be the one
   element on the page that ignores the light/dark palette around it.

   Loaded from CDN. The app is already served over a network and already pulls
   fonts from one; vendoring is a change confined to the URL below.

   If Monaco fails to load for any reason, `mount` returns a textarea wearing the
   same interface. A student who cannot reach a CDN must still be able to type. */

(function (global) {
  const CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min";
  let loading = null;

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /* Monaco wants six-digit hex and throws on anything else, so every value is
     validated before it is handed over rather than trusted from the stylesheet. */
  function hex(name, fallback) {
    const v = css(name, fallback);
    return /^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback;
  }

  function defineThemes(monaco) {
    for (const [name, base, surface, ink] of [
      ["clive-light", "vs", hex("--surface", "#ffffff"), hex("--ink", "#14201f")],
      ["clive-dark", "vs-dark", hex("--surface", "#161d1c"), hex("--ink", "#e6ece9")],
    ]) {
      monaco.editor.defineTheme(name, {
        base, inherit: true, rules: [],
        colors: {
          "editor.background": surface,
          "editor.foreground": ink,
          "editorLineNumber.foreground": hex("--ink-3", "#8b9997"),
          "editorGutter.background": surface,
        },
      });
    }
  }

  function isDark() {
    const explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit === "dark";
    return matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function load() {
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = `${CDN}/vs/loader.js`;
      tag.onerror = () => reject(new Error("Monaco could not be loaded."));
      tag.onload = () => {
        global.require.config({ paths: { vs: `${CDN}/vs` } });
        global.require(["vs/editor/editor.main"], () => {
          defineThemes(global.monaco);
          resolve(global.monaco);
        }, reject);
      };
      document.head.append(tag);
    });
    return loading;
  }

  function textareaFallback(host, opts) {
    const ta = document.createElement("textarea");
    ta.value = opts.value || "";
    ta.readOnly = !!opts.readOnly;
    ta.spellcheck = false;
    ta.style.cssText =
      "width:100%;min-height:320px;font-family:var(--mono,monospace);font-size:13px;" +
      "line-height:1.5;padding:10px 12px;border:1px solid var(--line-2,#ccc);" +
      "border-radius:8px;background:var(--paper,#fff);color:var(--ink,#000);resize:vertical";
    ta.addEventListener("input", () => opts.onChange && opts.onChange(ta.value));
    host.replaceChildren(ta);
    return {
      getValue: () => ta.value,
      setValue: (v) => { ta.value = v; },
      layout() {},
      dispose() {},
    };
  }

  /* Returns the handle synchronously so callers never juggle a promise. Monaco
     swaps itself in when it arrives; edits made before then are carried across. */
  function mount(host, opts = {}) {
    const fallback = textareaFallback(host, opts);
    let live = fallback;

    load().then((monaco) => {
      const carried = live.getValue();
      host.replaceChildren();
      host.style.minHeight = "320px";
      const editor = monaco.editor.create(host, {
        value: carried,
        language: opts.language || "c",
        readOnly: !!opts.readOnly,
        theme: isDark() ? "clive-dark" : "clive-light",
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        fontFamily: css("--mono", "monospace"),
        tabSize: 4,
        renderWhitespace: "selection",
      });
      editor.onDidChangeModelContent(() => opts.onChange && opts.onChange(editor.getValue()));
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        monaco.editor.setTheme(isDark() ? "clive-dark" : "clive-light");
      });
      live = {
        getValue: () => editor.getValue(),
        setValue: (v) => { if (editor.getValue() !== v) editor.setValue(v); },
        layout: () => editor.layout(),
        dispose: () => editor.dispose(),
      };
    }).catch(() => { /* the textarea is already mounted and works */ });

    return {
      getValue: () => live.getValue(),
      setValue: (v) => live.setValue(v),
      layout: () => live.layout(),
      dispose: () => live.dispose(),
    };
  }

  global.CLiveEditor = { mount };
})(window);

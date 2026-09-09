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

  /* `--surface`/`--ink`/`--ink-3` are the same variable names in both the light and
     dark halves of the page's stylesheet, so a `getComputedStyle` read only ever
     returns whichever palette is live in the DOM right now -- it cannot answer "what
     is the dark value" while the page is light. Reading them once for both theme
     names (as a loop over both names sharing one read used to do) would bake
     whichever palette happens to be active into BOTH Monaco themes, leaving the
     other one silently wrong until something redefines it. So this is never called
     once up front for both names: every call site that is about to *apply* a theme
     calls this for that one name immediately first, which is the only way to
     guarantee the read happens while the DOM is actually in that theme's state. */
  const THEME_FALLBACK = {
    "clive-light": { base: "vs", surface: "#ffffff", ink: "#14201f", ink3: "#8b9997" },
    "clive-dark": { base: "vs-dark", surface: "#161d1c", ink: "#e6ece9", ink3: "#6f807c" },
  };

  function defineTheme(monaco, name) {
    const fb = THEME_FALLBACK[name];
    const surface = hex("--surface", fb.surface);
    monaco.editor.defineTheme(name, {
      base: fb.base, inherit: true, rules: [],
      colors: {
        "editor.background": surface,
        "editor.foreground": hex("--ink", fb.ink),
        "editorLineNumber.foreground": hex("--ink-3", fb.ink3),
        "editorGutter.background": surface,
      },
    });
  }

  function currentThemeName() {
    return isDark() ? "clive-dark" : "clive-light";
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
      // Defined immediately before it is applied, so the read below always reflects
      // whatever the DOM's palette actually is at this instant -- see defineTheme.
      const initialTheme = currentThemeName();
      defineTheme(monaco, initialTheme);
      const editor = monaco.editor.create(host, {
        value: carried,
        language: opts.language || "c",
        readOnly: !!opts.readOnly,
        theme: initialTheme,
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
        const name = currentThemeName();
        defineTheme(monaco, name);
        monaco.editor.setTheme(name);
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

/* Monaco, lazy-loaded and bundled locally (no CDN): the editor core plus Python only. */
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { useEffect, useRef } from "react";
import type { CodeEditorProps } from "./CodeEditor";

(self as any).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

const SNIPPETS: [string, string, string][] = [
  ["fastinput", "Fast input", "import sys\ninput = sys.stdin.readline\n"],
  ["heapq", "heapq import", "import heapq\n"],
  ["defaultdict", "defaultdict", "from collections import defaultdict\n${1:d} = defaultdict(${2:int})\n"],
  ["lowbit", "lowest set bit", "${1:x} & -${1:x}"],
  ["popcount", "popcount", "bin(${1:x}).count('1')"],
  ["bits", "iterate bitmask", "for ${1:i} in range(${2:n}):\n    if ${3:mask} >> ${1:i} & 1:\n        ${4:pass}"],
];

let snippetsRegistered = false;

export default function MonacoEditor(p: CodeEditorProps) {
  const ref = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const cb = useRef(p);
  cb.current = p;

  useEffect(() => {
    monaco.editor.defineTheme("algoarena", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "keyword", foreground: p.accent.slice(1) },
        { token: "comment", foreground: "64748b", fontStyle: "italic" },
        { token: "number", foreground: "fbbf24" },
        { token: "string", foreground: "86efac" },
      ],
      colors: {
        "editor.background": "#020617",
        "editorCursor.foreground": p.accent,
        "editor.lineHighlightBackground": "#0f172a",
        "editorLineNumber.foreground": "#334155",
        "editor.selectionBackground": "#1e3a8a",
      },
    });
    monaco.editor.setTheme("algoarena");
  }, [p.accent]);

  const onMount: OnMount = (editor) => {
    ref.current = editor;
    (window as any).__algoarenaEditor = editor;
    editor.onDidPaste((e) => cb.current.onPaste?.(editor.getModel()?.getValueInRange(e.range).length ?? 0));
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => cb.current.onRun?.());
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => cb.current.onSubmit?.());
    if (!snippetsRegistered) {
      snippetsRegistered = true;
      monaco.languages.registerCompletionItemProvider("python", {
        provideCompletionItems: (model, pos) => {
          const word = model.getWordUntilPosition(pos);
          const range = { startLineNumber: pos.lineNumber, endLineNumber: pos.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
          return {
            suggestions: SNIPPETS.map(([label, detail, text]) => ({
              label,
              detail,
              kind: monaco.languages.CompletionItemKind.Snippet,
              insertText: text,
              insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
              range,
            })),
          };
        },
      });
    }
  };

  return (
    <Editor
      height="100%"
      language={p.language === "python" ? "python" : p.language}
      value={p.value}
      theme="algoarena"
      onChange={(v) => p.onChange(v ?? "")}
      onMount={onMount}
      options={{
        minimap: { enabled: false },
        fontSize: p.fontSize,
        fontFamily: "JetBrains Mono, ui-monospace, monospace",
        bracketPairColorization: { enabled: true },
        autoIndent: "full",
        tabSize: 4,
        scrollBeyondLastLine: false,
        automaticLayout: true,
        accessibilitySupport: "auto",
      }}
    />
  );
}

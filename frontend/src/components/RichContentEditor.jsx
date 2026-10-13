import { useEffect } from 'react'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { TextStyleKit } from '@tiptap/extension-text-style'

// WYSIWYG editor for page content rendered by the *browser* — currently the
// About page. Deliberately a separate component from
// components/generate/RichTextEditor.jsx: that one is cut down to the marks
// app/pdf/rich_text.py can draw into a PDF, so widening it would let an admin
// author headings, lists and colours that the PDF silently strips. The
// allowlist that bounds this editor lives in app/services/site_config.py, which
// sanitizes on write.
const EXTENSIONS = [
  StarterKit.configure({
    link: { openOnClick: false, defaultProtocol: 'https' },
    codeBlock: false,
    code: false,
  }),
  TextStyleKit.configure({ lineHeight: false, backgroundColor: false }),
]

// Values are what lands in the style attribute, so they must survive the
// server-side CSS allowlist (font-family / font-size in site_config.py).
const FONTS = [
  { label: 'Default', value: '' },
  { label: 'Sans serif', value: 'Arial, Helvetica, sans-serif' },
  { label: 'Serif', value: 'Georgia, "Times New Roman", serif' },
  { label: 'Monospace', value: '"Courier New", monospace' },
]

const SIZES = [
  { label: 'Default', value: '' },
  { label: 'Small', value: '12px' },
  { label: 'Normal', value: '16px' },
  { label: 'Large', value: '20px' },
  { label: 'Huge', value: '28px' },
]

function ToolbarButton({ label, title, active, onClick }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={!!active}
      onMouseDown={e => e.preventDefault()} // keep the editor selection/focus
      onClick={onClick}
      className={`px-1.5 py-0.5 rounded text-xs leading-none border ${
        active
          ? 'bg-purple-100 border-purple-300 text-purple-800'
          : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  )
}

function Divider() {
  return <span className="w-px self-stretch bg-gray-200" aria-hidden="true" />
}

// value: HTML string (or null while it is still loading).
// onChange: called with the editor's HTML on every edit.
// label: accessible name for the editable area.
export default function RichContentEditor({ value, onChange, label, rows = 16 }) {
  const editor = useEditor({
    extensions: EXTENSIONS,
    content: value ?? '',
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
    editorProps: {
      attributes: {
        class: 'rich-content px-3 py-2 text-sm focus:outline-none',
        style: `min-height: ${rows * 1.5}rem`,
        'aria-label': label,
      },
    },
  })

  // Fill in externally-arriving content only while the editor is still empty,
  // so a slow fetch never clobbers what the admin has already typed.
  useEffect(() => {
    if (editor && value && editor.isEmpty && value !== editor.getHTML()) {
      editor.commands.setContent(value)
    }
  }, [editor, value])

  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e?.isActive('bold') ?? false,
      italic: e?.isActive('italic') ?? false,
      underline: e?.isActive('underline') ?? false,
      strike: e?.isActive('strike') ?? false,
      bulletList: e?.isActive('bulletList') ?? false,
      orderedList: e?.isActive('orderedList') ?? false,
      h1: e?.isActive('heading', { level: 1 }) ?? false,
      h2: e?.isActive('heading', { level: 2 }) ?? false,
      h3: e?.isActive('heading', { level: 3 }) ?? false,
      link: e?.isActive('link') ?? false,
      fontFamily: e?.getAttributes('textStyle')?.fontFamily ?? '',
      fontSize: e?.getAttributes('textStyle')?.fontSize ?? '',
      color: e?.getAttributes('textStyle')?.color ?? '#111827',
    }),
  })

  if (!editor) return null

  function toggleLink() {
    if (editor.isActive('link')) {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    const url = window.prompt('Link URL (e.g. https://www.pillora.com.sg)')
    if (!url) return
    editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run()
  }

  // An empty option means "clear the mark" rather than "set it to empty".
  function pickFont(v) {
    const chain = editor.chain().focus()
    ;(v ? chain.setFontFamily(v) : chain.unsetFontFamily()).run()
  }

  function pickSize(v) {
    const chain = editor.chain().focus()
    ;(v ? chain.setFontSize(v) : chain.unsetFontSize()).run()
  }

  return (
    <div className="border border-gray-300 rounded bg-white">
      <div className="flex flex-wrap items-center gap-1 px-1.5 py-1 border-b border-gray-200">
        <ToolbarButton label={<b>B</b>} title="Bold" active={state.bold}
          onClick={() => editor.chain().focus().toggleBold().run()} />
        <ToolbarButton label={<i>I</i>} title="Italic" active={state.italic}
          onClick={() => editor.chain().focus().toggleItalic().run()} />
        <ToolbarButton label={<u>U</u>} title="Underline" active={state.underline}
          onClick={() => editor.chain().focus().toggleUnderline().run()} />
        <ToolbarButton label={<s>S</s>} title="Strikethrough" active={state.strike}
          onClick={() => editor.chain().focus().toggleStrike().run()} />

        <Divider />

        <ToolbarButton label="H1" title="Heading 1" active={state.h1}
          onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} />
        <ToolbarButton label="H2" title="Heading 2" active={state.h2}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} />
        <ToolbarButton label="H3" title="Heading 3" active={state.h3}
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} />

        <Divider />

        <ToolbarButton label="• List" title="Bullet list" active={state.bulletList}
          onClick={() => editor.chain().focus().toggleBulletList().run()} />
        <ToolbarButton label="1. List" title="Numbered list" active={state.orderedList}
          onClick={() => editor.chain().focus().toggleOrderedList().run()} />

        <Divider />

        <select
          value={state.fontFamily}
          aria-label="Font"
          onMouseDown={e => e.stopPropagation()}
          onChange={e => pickFont(e.target.value)}
          className="border border-gray-300 rounded px-1 py-0.5 text-xs text-gray-700 bg-white"
        >
          {FONTS.map(f => <option key={f.label} value={f.value}>{f.label}</option>)}
        </select>

        <select
          value={state.fontSize}
          aria-label="Font size"
          onChange={e => pickSize(e.target.value)}
          className="border border-gray-300 rounded px-1 py-0.5 text-xs text-gray-700 bg-white"
        >
          {SIZES.map(s => <option key={s.label} value={s.value}>{s.label}</option>)}
        </select>

        <input
          type="color"
          value={state.color}
          aria-label="Text colour"
          onChange={e => editor.chain().focus().setColor(e.target.value).run()}
          className="h-6 w-7 rounded border border-gray-300 bg-white p-0.5"
        />
        <ToolbarButton label="A̶" title="Clear colour"
          onClick={() => editor.chain().focus().unsetColor().run()} />

        <Divider />

        <ToolbarButton label="🔗" title={state.link ? 'Remove link' : 'Add link'} active={state.link}
          onClick={toggleLink} />
      </div>
      <EditorContent editor={editor} />
    </div>
  )
}

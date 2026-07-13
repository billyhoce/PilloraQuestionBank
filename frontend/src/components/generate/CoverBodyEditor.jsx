import { useEffect } from 'react'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

// Rich-text editor for the cover letter body. Deliberately limited to the
// marks the PDF cover renderer supports (see app/pdf/cover_body.py): plain
// paragraphs plus bold / italic / underline / link. Everything richer
// (headings, lists, code, …) is disabled so the editor can't produce markup
// the backend would strip.
const EXTENSIONS = [
  StarterKit.configure({
    heading: false,
    bulletList: false,
    orderedList: false,
    listItem: false,
    listKeymap: false,
    blockquote: false,
    code: false,
    codeBlock: false,
    horizontalRule: false,
    strike: false,
    link: { openOnClick: false, defaultProtocol: 'https' },
  }),
]

function ToolbarButton({ label, title, active, onClick }) {
  return (
    <button
      type="button"
      title={title}
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

// value: HTML string (or null while the defaults are still loading).
// onChange: called with the editor's HTML on every edit.
export default function CoverBodyEditor({ value, onChange }) {
  const editor = useEditor({
    extensions: EXTENSIONS,
    content: value ?? '',
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
    editorProps: {
      attributes: {
        class: 'cover-body-editor min-h-[7rem] max-h-64 overflow-y-auto px-2 py-1 text-xs focus:outline-none',
        'aria-label': 'Cover letter / message',
      },
    },
  })

  // Fill in externally-arriving content (the fetched defaults) only while the
  // editor is still empty, so a slow fetch never clobbers the user's typing.
  useEffect(() => {
    if (editor && value && editor.isEmpty && value !== editor.getHTML()) {
      editor.commands.setContent(value)
    }
  }, [editor, value])

  const marks = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e?.isActive('bold') ?? false,
      italic: e?.isActive('italic') ?? false,
      underline: e?.isActive('underline') ?? false,
      link: e?.isActive('link') ?? false,
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

  return (
    <div className="border border-gray-300 rounded bg-white">
      <div className="flex gap-1 px-1.5 py-1 border-b border-gray-200">
        <ToolbarButton
          label={<b>B</b>}
          title="Bold"
          active={marks.bold}
          onClick={() => editor.chain().focus().toggleBold().run()}
        />
        <ToolbarButton
          label={<i>I</i>}
          title="Italic"
          active={marks.italic}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        />
        <ToolbarButton
          label={<u>U</u>}
          title="Underline"
          active={marks.underline}
          onClick={() => editor.chain().focus().toggleUnderline().run()}
        />
        <ToolbarButton
          label="🔗"
          title={marks.link ? 'Remove link' : 'Add link'}
          active={marks.link}
          onClick={toggleLink}
        />
      </div>
      <EditorContent editor={editor} />
    </div>
  )
}

# CLAUDE.md

This is a multi-project workspace. Each project lives in its own subdirectory.

## Projects

- `act-log/` — יומן עבודה לאנשי צוות אקט. Next.js 14, TypeScript, Supabase, iCount integration. Deployed on Vercel.
- `kesef-al-haritzpa/` — אפליקציית ניהול מנויים. זיהוי מנויים אוטומטי, ניתוח מיילים, ביטול בלחיצה. בפיתוח.
- `_files/` — קבצים, צילומי מסך, מסמכי אקט.
- `_archive/` — פרויקטים ישנים.

## How to work

**Always open Claude Code from within the specific project directory**, not from this workspace root.
This ensures Claude's context is focused on the correct project.

```
cd act-log
cd kesef-al-haritzpa
claude
```

## Coding Standards

- TypeScript project using React 18
- Always use functional components with hooks
- Prefer named exports over default exports
- Tests go in `__tests__` folders next to their source files
- Use CSS modules for styling
- Error messages should be user-friendly — never show raw error objects to the user

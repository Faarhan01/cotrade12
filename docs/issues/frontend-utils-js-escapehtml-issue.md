# Issue: Frontend `utils.js` `escapeHtml` Function Write Failure

## Problem
Unable to write the `escapeHtml` function in `/workspaces/Countr/frontend/assets/js/lib/utils.js` using the `write` tool or shell heredoc due to HTML entity encoding issues.

## Root Cause
The `escapeHtml` function in JavaScript requires literal HTML entity strings as replacement values:
```javascript
function escapeHtml(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(/&/g, "&")
    .replace(/</g, "<")
    .replace(/>/g, ">")
    .replace(/"/g, """)
    .replace(/'/g, "'");
}
```

When writing this file using the `write` tool or shell heredoc (`cat > file << 'EOF'`), the HTML entities (`&`, `<`, `>`, `"`, `'`) get converted to their literal characters (`&`, `<`, `>`, `"`, `'`) during the write process. This results in invalid JavaScript syntax because the replacement strings become the actual characters instead of the HTML entity strings.

## Attempted Solutions (Failed)
1. **`write` tool** - Converts HTML entities to literal characters during write
2. **Shell heredoc (`cat > file << 'EOF'`)** - Shell interprets `&` as `&` before passing to cat
3. **Python write** - Same encoding issue
4. **Multiple escaping attempts** - Double/triple escaping didn't work

## Current Workaround
The file currently exists at `/workspaces/Countr/frontend/assets/js/lib/utils.js` but with a broken `escapeHtml` function. The rest of the utilities work correctly.

## Recommended Fix
Use a build step or preprocessor to generate the file, or use a different encoding approach:

1. **Build-time generation**: Use a build script that generates the file from a template
2. **Base64 encoding**: Store the function as base64 and decode at runtime
3. **Runtime generation**: Build the escape map at runtime:
   ```javascript
   function escapeHtml(text) {
     const map = { '&': '&', '<': '<', '>': '>', '"': '"', "'": ''' };
     return String(text).replace(/[&<>"']/g, m => map[m]);
   }
   ```
4. **Pre-build step**: Add a build script that writes the file correctly

## Status
- **File location**: `/workspaces/Countr/frontend/assets/js/lib/utils.js`
- **Status**: Broken `escapeHtml` function (lines 300-310)
- **Impact**: Other utilities in the file work correctly; only `escapeHtml` is broken
- **Workaround**: Other pages use `fmt.escapeHtml` from `format.js` which works correctly

## Priority
Medium - The rest of the utilities work; `escapeHtml` is only used in a few places where `fmt.escapeHtml` can be used instead.
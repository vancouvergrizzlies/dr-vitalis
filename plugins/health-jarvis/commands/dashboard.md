---
description: Open the Health Jarvis dashboard in your browser
---

The user wants to open the dashboard.

1. Run a small bash command to open the dashboard HTML in the default browser:
   - macOS: `open "$HOME/.health-jarvis/dashboard.html"`
   - Linux: `xdg-open "$HOME/.health-jarvis/dashboard.html"`
   - Windows/WSL: `explorer.exe "$(wslpath -w "$HOME/.health-jarvis/dashboard.html")"`

   Detect the platform via `uname` and run the right one. If the file doesn't
   exist yet, tell the user to first add at least one voice with `/council
   add @handle` so the dashboard is generated.

2. Report the path you opened.

Don't read or render the HTML in chat — just open it.

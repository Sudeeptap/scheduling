# Super Clinic — Diagrams

Mermaid diagram source files for the Super Clinic POC design.

| File | Diagram |
|------|---------|
| `01-system-architecture.mmd` | System Architecture — component topology and data flow |
| `02-booking-flow.mmd` | Booking Flow — full decision tree including alternates and double-booking retry |
| `03-sequence-diagram.mmd` | Sequence Diagram — Scenario 1 (successful booking) and Scenario 2 (alternate slot/doctor) |
| `04-er-diagram.mmd` | ER Diagram — all database tables and relationships |

## Viewing the diagrams

**Option 1 — Mermaid Live Editor**
Paste the contents of any `.mmd` file into https://mermaid.live

**Option 2 — VS Code / Kiro**
Install the [Mermaid Preview](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension.
Open any `.mmd` file and use the preview pane.

**Option 3 — draw.io**
Open draw.io → Extras → Edit Diagram → paste the Mermaid source.
draw.io will convert it to an editable diagram.

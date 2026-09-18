# Web application boundary

Owner: Agent B. Runtime: Ryzen AI 9 laptop browser.

Agent A defines only the contract boundary here; React/Vite components, accessibility behavior, adapters, and generated TypeScript integration remain Agent B-owned. The web app calls the laptop Core Backend and local Speech Gateway only. It never calls MI300.

Student routes must not receive or retain answer keys, model confidence, teacher controls, evidence, or full teacher-review Lesson objects.

## Stage 03 camera and upload flow

`/capture` now provides a keyboard-operable camera preview, camera selection,
photo capture, and a file-upload fallback. Camera permission failure never
blocks the file path. Before a photo is accepted, the browser:

- corrects the decoded orientation by drawing through a canvas (which also
  removes EXIF metadata);
- crops to the selected bounded rectangle (full-page crop is the default);
- limits the long edge to 4096 px and compresses to JPEG no larger than 8 MiB;
- checks minimum 640×480 resolution, blur, underexposure, overexposure, and
  supported type; and
- keeps only a short-lived object URL for the local preview.

Blur and exposure are warnings that require an explicit user override. Invalid
type, low resolution, and over-size output are blocking checks; Core Backend
must repeat validation. The current v0.1 multipart contract is
`POST /api/lessons/analyze` with `image`, `language=nan-TW`, and
`use_fixture_on_failure=true`. The runtime handler is still Agent A Stage 04
work, so Mock mode and the clearly-labelled frontend fixture remain available.

Run the Stage 03 checks from the repository root:

```powershell
cd apps/web
npm run test
npm run typecheck
npm run build
```

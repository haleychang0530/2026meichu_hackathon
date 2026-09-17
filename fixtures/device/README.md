# Device test fixtures

These fixtures are deliberately synthetic and contain no names, faces, student recordings, or other identifying information.

- `audio/synthetic-prompt.wav`: 1.2-second PCM tone sequence.
- `audio/synthetic-response.wav`: 1.8-second PCM three-tone sequence.
- `audio/synthetic-fallback.wav`: 0.9-second PCM pulse sequence.
- `lesson-images/lesson-shapes.svg`: geometric shapes and color labels.
- `lesson-images/lesson-market.svg`: a person-free fruit stall illustration.
- `lesson-images/lesson-weather.svg`: sun, cloud, and rain illustration.

The audio files are transport and playback fixtures only. They intentionally do not claim to be Breeze-ASR semantic accuracy goldens; Stage 05 should add a separately reviewed speech set if one is needed.

Run `scripts/generate_device_fixtures.ps1` after changing the generator. It rewrites the WAV files and `manifest.json` with SHA-256 checksums.

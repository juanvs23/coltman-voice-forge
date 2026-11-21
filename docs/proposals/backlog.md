# Backlog — unprioritised

Ideas that were raised, judged useful, and deliberately not scheduled. Each one
says what would make it worth starting.

| Idea | Why it is not a phase | Trigger to start |
|---|---|---|
| **Emotion presets** (`terror-susurro`, `cierre-amargo`) stored per project | A script can already express the axes inline; presets are sugar | When the same emotion vector is pasted in three scripts |
| **Per-voice `conditioning: speaker \| icl`** | ICL over-generates (2.1× longer on a short line) and the neutral rule makes it an exception by nature | A character whose reference is acted on purpose |
| **Bilingual scripts** (same character, two languages) | Ming speaks seven languages, but a character voicing two of them is a casting decision nobody has needed yet | A video with two language tracks |
| **Diarisation of a long recording** to cut references automatically | Needs a diarisation model (Nemotron/Pyannote) and a new adapter | When a source interview must become five voices |
| **Loudness report per render** (LUFS integrated, true peak) | The master already targets −14 LUFS; the report only proves it | Before publishing to a platform that normalises |
| **MCP server** exposing the catalog as tools | The REST API already covers agents with an HTTP client | When an agent must narrate without a terminal |
| **Duration guard** per line | Measured once (+25 % on a strong emotion); the operator declined policing | The first bloated line that reaches a master |
| **Voice export/import bundle** (voice.json + ref.wav in one file) | The catalog directory is already portable | Moving voices between machines |

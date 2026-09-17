# Web application boundary

Owner: Agent B. Runtime: Ryzen AI 9 laptop browser.

Agent A defines only the contract boundary here; React/Vite components, accessibility behavior, adapters, and generated TypeScript integration remain Agent B-owned. The web app calls the laptop Core Backend and local Speech Gateway only. It never calls MI300.

Student routes must not receive or retain answer keys, model confidence, teacher controls, evidence, or full teacher-review Lesson objects.

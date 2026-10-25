import re

with open("src/vibeplay/templates/index.html", "r") as f:
    content = f.read()

# Update vibe presets in index.html
vibe_options = """            <option value="melancholic">Melancholic (Moody, Contemplative)</option>
            <option value="energetic">Energetic (High Energy, Upbeat)</option>
            <option value="euphoric">Euphoric (Happy, High Energy)</option>
            <option value="focus">Focus (Steady, Non-distracting)</option>
            <option value="dark">Dark (Minor Key, Heavy)</option>
            <option value="romantic">Romantic (Major, Low Energy)</option>
            <option value="ambient">Ambient (Low Energy, Low Danceability)</option>"""

content = content.replace('<option value="melancholy">Melancholy (Moody, Contemplative)</option>', vibe_options)

# Update mood filter in index.html
mood_filter_options = """        <option value="sad">Sad / Melancholy (≥ 50%)</option>
        <option value="energetic">Energetic (≥ 50%)</option>
        <option value="euphoric">Euphoric (≥ 50%)</option>
        <option value="focus">Focus (≥ 50%)</option>
        <option value="dark">Dark (≥ 50%)</option>
        <option value="romantic">Romantic (≥ 50%)</option>
        <option value="ambient">Ambient (≥ 50%)</option>"""

content = content.replace('<option value="sad">Sad / Melancholy (≥ 50%)</option>', mood_filter_options)

# Add mood chips
mood_chips = """      <button type="button" class="mood-chip" data-mood="electronic" onclick="selectMoodChip('electronic')">
        <span class="dot-indicator dot-cyan"></span>
        <span>Electronic</span>
      </button>
      <button type="button" class="mood-chip" data-mood="energetic" onclick="selectMoodChip('energetic')">
        <span class="dot-indicator dot-red"></span>
        <span>Energetic</span>
      </button>
      <button type="button" class="mood-chip" data-mood="focus" onclick="selectMoodChip('focus')">
        <span class="dot-indicator dot-cyan"></span>
        <span>Focus</span>
      </button>
      <button type="button" class="mood-chip" data-mood="romantic" onclick="selectMoodChip('romantic')">
        <span class="dot-indicator dot-purple"></span>
        <span>Romantic</span>
      </button>
      <button type="button" class="mood-chip" data-mood="ambient" onclick="selectMoodChip('ambient')">
        <span class="dot-indicator dot-cyan"></span>
        <span>Ambient</span>
      </button>"""

content = content.replace("""      <button type="button" class="mood-chip" data-mood="electronic" onclick="selectMoodChip('electronic')">
        <span class="dot-indicator dot-cyan"></span>
        <span>Electronic</span>
      </button>""", mood_chips)

with open("src/vibeplay/templates/index.html", "w") as f:
    f.write(content)

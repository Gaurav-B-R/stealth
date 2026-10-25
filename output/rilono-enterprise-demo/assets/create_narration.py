import json
import pathlib
import subprocess
import wave

ROOT = pathlib.Path(__file__).resolve().parent
FFMPEG = '/private/tmp/rilono-video-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
SCENES = [
    ('intro', 'Meet Rilono Enterprise, a shared workspace built for your study-abroad consultancy.'),
    ('dashboard', 'Start with a clear view of active cases, your client pipeline, and upcoming work, so your team knows what needs attention.'),
    ('leads', "Capture enquiries through branded forms. Review each lead and its source, then open a prefilled intake when they're ready to become a client."),
    ('student_journey', "Here is Ananya's student file. Her destination, study plans, and application journey stay together, with country-specific stages and case details that guide the next step."),
    ('documents_ai_review', 'Keep passports, funding evidence, and supporting documents with the case. AI checks flag potential inconsistencies, while Deep Scan reviews the wider dossier.'),
    ('course_finder', "Explore courses by destination, level, budget, and entry requirements. Build a personalized AI shortlist from Rilono's saved catalog, and keep selected options on the student's file."),
    ('assistant', 'Ask Rilono AI about your workspace. Get context on client progress, documents, and upcoming tasks, without searching through every record yourself.'),
    ('team_calendar', "Coordinate follow-ups and key dates in the calendar. Give counselors and managers roles and access that match the work they're responsible for."),
    ('outro', 'From first enquiry to the next milestone. Rilono Enterprise. Book a demo.'),
]

def main():
    result = []
    for ident, text in SCENES:
        source = ROOT / ('narration-' + ident + '.txt')
        aiff = ROOT / ('narration-' + ident + '.aiff')
        audio = ROOT / ('narration-' + ident + '.wav')
        source.write_text(text, encoding='utf-8')
        subprocess.run(['/usr/bin/say', '-v', 'Daniel', '-r', '163', '-f', str(source), '-o', str(aiff)], check=True)
        subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(aiff), '-af', 'highpass=f=75,lowpass=f=11000,loudnorm=I=-17:TP=-2:LRA=7,adelay=200,apad=pad_dur=0.4', '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', str(audio)], check=True)
        with wave.open(str(audio)) as wav:
            duration = wav.getnframes() / wav.getframerate()
        row = {'id': ident, 'text': text, 'duration': duration, 'audio': str(audio), 'voice': 'Daniel', 'words_per_minute': 163}
        result.append(row)
        print(json.dumps(row), flush=True)
    (ROOT / 'narration.json').write_text(json.dumps({'total_duration': sum(r['duration'] for r in result), 'scenes': result}, indent=2), encoding='utf-8')
    (ROOT / 'narration.txt').write_text('\n\n'.join(ident.upper().replace('_',' ')+'\n'+text for ident,text in SCENES)+'\n', encoding='utf-8')
    print('TOTAL_SECONDS', round(sum(r['duration'] for r in result), 3), flush=True)
    print('WORDS', sum(len(t.split()) for _,t in SCENES), flush=True)

if __name__ == '__main__':
    main()

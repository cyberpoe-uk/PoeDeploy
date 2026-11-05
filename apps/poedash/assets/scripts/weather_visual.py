"""Small original SVG weather illustrations; no downloads or animation timers."""

def condition(code, is_day=True):
    if code==0:return ('clear','Clear sky' if is_day else 'Clear night','#fbbf24' if is_day else '#a5b4fc')
    if code in (1,2):return ('partly','Mostly clear' if code==1 else 'Partly cloudy','#fbbf24')
    if code==3:return ('cloud','Overcast','#94a3b8')
    if code in (45,48):return ('fog','Fog','#a5b4c4')
    if code in (51,53,55,56,57):return ('rain','Drizzle' if code<56 else 'Freezing drizzle','#60a5fa')
    if code in (61,63,65,66,67,80,81,82):return ('rain','Freezing rain' if code in (66,67) else 'Rain showers' if code>=80 else 'Rain','#60a5fa')
    if code in (71,73,75,77,85,86):return ('snow','Snow showers' if code>=85 else 'Snow','#a5e3f3')
    if code in (95,96,99):return ('storm','Thunderstorm','#c084fc')
    return ('unknown','Weather unavailable','#94a3b8')


def icon_svg(code,is_day=True):
    kind,_,color=condition(code,is_day)
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96" viewBox="0 0 128 96">']
    if kind in ('clear','partly'):
        if is_day:
            parts.append('<g stroke="#fbbf24" stroke-width="4" stroke-linecap="round"><path d="M47 8v6m0 48v6M17 38h6m48 0h6M26 17l5 5m32 32l5 5M26 59l5-5m32-32l5-5"/></g><circle cx="47" cy="38" r="17" fill="#fcd34d"/>')
        else:
            parts.append('<path d="M60 13a26 26 0 1 0 17 43A24 24 0 0 1 60 13" fill="#c7d2fe"/><g fill="#fde68a"><circle cx="87" cy="20" r="2"/><circle cx="98" cy="39" r="3"/></g>')
    if kind not in ('clear','unknown'):
        parts.append('<path d="M32 66a17 17 0 0 1-2-34 23 23 0 0 1 43-6 18 18 0 0 1 23 16 12 12 0 0 1-3 24Z" fill="#dce7f3"/><path d="M32 66h61a12 12 0 0 0 12-10H25a17 17 0 0 0 7 10" fill="#b7c9dd"/>')
    if kind=='rain':parts.append('<path d="m40 75-5 10m23-10-5 10m23-10-5 10m23-10-5 10" stroke="#60a5fa" stroke-width="4" stroke-linecap="round"/>')
    if kind=='storm':parts.append('<path d="m64 59-15 22h14l-6 14 25-27H67l7-9Z" fill="#fbbf24"/>')
    if kind=='snow':
        parts.append('<g stroke="#a5e3f3" stroke-width="2.5" stroke-linecap="round">')
        for x in (39,64,89):parts.append(f'<path d="M{x} 74v14m-6-10 12 6m-12 0 12-6"/>')
        parts.append('</g>')
    if kind=='fog':parts.append('<path d="M22 76h80M32 84h62" stroke="#a5b4c4" stroke-width="4" stroke-linecap="round"/>')
    if kind=='unknown':parts.append('<circle cx="64" cy="45" r="26" fill="none" stroke="#94a3b8" stroke-width="3"/><text x="64" y="55" fill="#94a3b8" font-size="30" text-anchor="middle">?</text>')
    return ''.join(parts)+'</svg>'

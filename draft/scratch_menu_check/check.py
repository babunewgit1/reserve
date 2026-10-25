import re

html = open('/Users/babu/File/Work Space/Code/draft/desktop.html').read()
# Normalize </a\n> or </a \n> to </a>
html = re.sub(r'</a\s*\n\s*>', '</a>', html)

def clean(text):
    """Strip HTML tags, normalize whitespace"""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = text.replace('&amp;', '&').replace('&nbsp;', ' ').replace('&#x27;', "'")
    return re.sub(r'\s+', ' ', text).strip()

# Split by dropdown
dropdowns = re.split(r'class="mega-menu-dropdown w-dropdown"', html)[1:]

print('='*80)
print('  MENU ITEM NAME + LINK COMPARISON')
print('  desktop.html: megamenu-desktop vs mobile-version')
print('  (Text case IGNORED)')
print('='*80)

all_mismatches = []

for dd in dropdowns:
    name_m = re.search(r'<div class="menu_link_text-v2">([^<]+)</div>', dd)
    if not name_m:
        continue
    menu_name = name_m.group(1).strip()
    
    # Extract megamenu-desktop section only (may come before or after mobile-version)
    desk_m = re.search(r'class="megamenu-desktop[^"]*">(.*?)<div class="mobile-version">', dd, re.DOTALL)
    if not desk_m:
        # Try reverse order: mobile-version comes first, then megamenu-desktop
        desk_m = re.search(r'class="megamenu-desktop[^"]*">(.*?)$', dd, re.DOTALL)
    mob_m = re.search(r'<div class="mobile-version">(.*?)class="megamenu-desktop', dd, re.DOTALL)
    if not mob_m:
        mob_m = re.search(r'<div class="mobile-version">(.*)', dd, re.DOTALL)
    
    if not desk_m or not mob_m:
        print(f'\n⚠️ {menu_name}: Could not split sections')
        continue
    
    desk = desk_m.group(1)
    mob = mob_m.group(1)
    
    # ---- DESKTOP: Extract ALL <a href="/..."> items ----
    # Look for links that contain item text (megamenu-item-header OR megamenu-item-list-desc)
    d_items = []
    for a in re.finditer(r'<a\b[^>]*?href="(/[^"]*)"[^>]*?>(.*?)</a>', desk, re.DOTALL):
        href = a.group(1)
        inner = a.group(2)
        
        # Skip CTA buttons (megamenu-btn)
        if 'megamenu-btn' in a.group(0):
            continue
        
        # Find item text from various classes
        text = None
        for cls in ['megamenu-item-header', 'megamenu-item-list-desc', 'cp_middile_link_heading', 'cp_middile_link_text', 'liget_heading']:
            t_m = re.search(r'class="' + cls + r'[^"]*"[^>]*>(.*?)</p>', inner, re.DOTALL)
            if t_m:
                text = clean(t_m.group(1))
                break
        
        if text and href:
            d_items.append({'text': text, 'href': href})
    
    # ---- MOBILE: Extract ALL <a href="/..."> items ----
    m_items = []
    for a in re.finditer(r'<a\b[^>]*?href="(/[^"]*)"[^>]*?>(.*?)</a>', mob, re.DOTALL):
        href = a.group(1)
        inner = a.group(2)
        
        if 'megamenu-btn' in a.group(0):
            continue
        
        # Mobile items use paragraph-5 class
        t_m = re.search(r'class="paragraph-5"[^>]*>(.*?)</p>', inner, re.DOTALL)
        if t_m:
            text = clean(t_m.group(1))
            if text:
                m_items.append({'text': text, 'href': href})
    
    # ---- PRINT ----
    print(f'\n{"─"*80}')
    print(f'  📂 {menu_name}')
    print(f'{"─"*80}')
    print(f'  Desktop: {len(d_items)} items | Mobile: {len(m_items)} items')
    
    if len(d_items) != len(m_items):
        print(f'  ⚠️ COUNT MISMATCH!')
    
    # Print desktop items
    print(f'\n  DESKTOP:')
    for i, item in enumerate(d_items):
        print(f'    {i+1:>2}. {item["text"]:<42} → {item["href"]}')
    
    print(f'\n  MOBILE:')
    for i, item in enumerate(m_items):
        print(f'    {i+1:>2}. {item["text"]:<42} → {item["href"]}')
    
    # ---- COMPARE ----
    d_map = {item['text'].lower(): item['href'] for item in d_items}
    m_map = {item['text'].lower(): item['href'] for item in m_items}
    
    found_mismatch = False
    
    for key, href in d_map.items():
        if key not in m_map:
            print(f'\n  🔴 MISSING from Mobile: "{key}" → {href}')
            all_mismatches.append(f'[{menu_name}] Missing from Mobile: "{key}" → {href}')
            found_mismatch = True
    
    for key, href in m_map.items():
        if key not in d_map:
            print(f'\n  🔴 MISSING from Desktop: "{key}" → {href}')
            all_mismatches.append(f'[{menu_name}] Missing from Desktop: "{key}" → {href}')
            found_mismatch = True
    
    for key in d_map:
        if key in m_map and d_map[key] != m_map[key]:
            print(f'\n  🔴 LINK MISMATCH: "{key}"')
            print(f'     Desktop: {d_map[key]}')
            print(f'     Mobile:  {m_map[key]}')
            all_mismatches.append(f'[{menu_name}] Link Diff: "{key}" D={d_map[key]} M={m_map[key]}')
            found_mismatch = True
    
    if not found_mismatch:
        print(f'\n  ✅ All items and links MATCH')

print(f'\n\n{"="*80}')
print(f'  TOTAL MISMATCHES: {len(all_mismatches)}')
print(f'{"="*80}')
if all_mismatches:
    for i, m in enumerate(all_mismatches):
        print(f'  {i+1}. {m}')
else:
    print('  ✅ ZERO MISMATCHES! সব menu items ও links একই।')

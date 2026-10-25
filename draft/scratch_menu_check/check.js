const fs = require('fs');

const desktopHTML = fs.readFileSync('/Users/babu/File/Work Space/Code/draft/desktop.html', 'utf8');
const mobileHTML = fs.readFileSync('/Users/babu/File/Work Space/Code/draft/mobile.html', 'utf8');

function stripTags(str) {
    return str.replace(/<[^>]*>/g, '')
        .replace(/&amp;/g, '&')
        .replace(/&nbsp;/g, ' ')
        .replace(/&#x27;/g, "'")
        .replace(/\s+/g, ' ')
        .trim();
}

// ============================
// STEP 1: Extract ALL megamenu-desktop sections from desktop.html
// ============================
function extractDesktopMenuItems(html) {
    const items = [];
    // Find all dropdown sections
    const dropdowns = html.split(/class="mega-menu-dropdown w-dropdown"/);
    
    for (let i = 1; i < dropdowns.length; i++) {
        const section = dropdowns[i];
        
        // Get menu name
        const nameMatch = section.match(/<div class="menu_link_text-v2">([^<]+)<\/div>/);
        const menuName = nameMatch ? nameMatch[1].trim() : `Menu ${i}`;
        
        // Extract megamenu-desktop content only
        const desktopMatch = section.match(/class="megamenu-desktop[^"]*">([\s\S]*?)(?:<div class="mobile-version">|$)/);
        if (!desktopMatch) continue;
        
        const desktopContent = desktopMatch[1];
        
        // Extract all <a> tags with href from desktop section
        const linkRegex = /<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
        let m;
        while ((m = linkRegex.exec(desktopContent)) !== null) {
            const href = m[1].trim();
            const inner = m[2];
            
            // Get text from <p> tags inside
            const pTexts = [];
            const pRegex = /<p[^>]*>([^<]*)<\/p>/gi;
            let pm;
            while ((pm = pRegex.exec(inner)) !== null) {
                const t = stripTags(pm[1]);
                if (t && t.length > 1) pTexts.push(t);
            }
            
            // Also check for direct div text
            if (pTexts.length === 0) {
                const divRegex = /<div[^>]*>([^<]+)<\/div>/gi;
                let dm;
                while ((dm = divRegex.exec(inner)) !== null) {
                    const t = stripTags(dm[1]);
                    if (t && t.length > 2) pTexts.push(t);
                }
            }
            
            if (pTexts.length > 0 && href) {
                items.push({
                    menu: menuName,
                    text: pTexts[0],
                    href: href,
                    subText: pTexts.slice(1).join(' | ')
                });
            }
        }
    }
    return items;
}

// ============================
// STEP 2: Extract ALL mobile-version sections from mobile.html
// ============================
function extractMobileMenuItems(html) {
    const items = [];
    const dropdowns = html.split(/class="mega-menu-dropdown w-dropdown"/);
    
    for (let i = 1; i < dropdowns.length; i++) {
        const section = dropdowns[i];
        
        const nameMatch = section.match(/<div class="menu_link_text-v2">([^<]+)<\/div>/);
        const menuName = nameMatch ? nameMatch[1].trim() : `Menu ${i}`;
        
        // Extract mobile-version content only
        const mobileMatch = section.match(/<div class="mobile-version">([\s\S]*?)(?:<\/nav>)/);
        if (!mobileMatch) continue;
        
        const mobileContent = mobileMatch[1];
        
        // Extract all <a> tags with href
        const linkRegex = /<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
        let m;
        while ((m = linkRegex.exec(mobileContent)) !== null) {
            const href = m[1].trim();
            const inner = m[2];
            
            const pTexts = [];
            const pRegex = /<p[^>]*>([^<]*)<\/p>/gi;
            let pm;
            while ((pm = pRegex.exec(inner)) !== null) {
                const t = stripTags(pm[1]);
                if (t && t.length > 1) pTexts.push(t);
            }
            
            if (pTexts.length === 0) {
                const divRegex = /<div[^>]*>([^<]+)<\/div>/gi;
                let dm;
                while ((dm = divRegex.exec(inner)) !== null) {
                    const t = stripTags(dm[1]);
                    if (t && t.length > 2) pTexts.push(t);
                }
            }
            
            if (pTexts.length > 0 && href) {
                items.push({
                    menu: menuName,
                    text: pTexts[0],
                    href: href,
                    subText: pTexts.slice(1).join(' | ')
                });
            }
        }
    }
    return items;
}

const desktopItems = extractDesktopMenuItems(desktopHTML);
const mobileItems = extractMobileMenuItems(mobileHTML);

console.log('======================================================================');
console.log('  MENU ITEM & LINK COMPARISON');
console.log('  Source: desktop.html [megamenu-desktop] vs mobile.html [mobile-version]');
console.log('  Text case IGNORED — only actual word/link differences reported');
console.log('======================================================================');

console.log(`\n  Desktop items extracted: ${desktopItems.length}`);
console.log(`  Mobile items extracted:  ${mobileItems.length}`);

// ============================
// STEP 3: Compare
// ============================

// Build lookup: normalize text (lowercase, trim) -> [{href, menu}]
const dMap = new Map();
desktopItems.forEach(item => {
    const key = item.text.toLowerCase().replace(/\s+/g, ' ').trim();
    if (!dMap.has(key)) dMap.set(key, []);
    dMap.get(key).push(item);
});

const mMap = new Map();
mobileItems.forEach(item => {
    const key = item.text.toLowerCase().replace(/\s+/g, ' ').trim();
    if (!mMap.has(key)) mMap.set(key, []);
    mMap.get(key).push(item);
});

let totalMismatches = 0;
const mismatches = [];

// A. Items in Desktop but NOT in Mobile
console.log('\n\n📋 A. Items in DESKTOP but MISSING from MOBILE');
console.log('-'.repeat(50));
let missingCount = 0;
for (const [key, dItems] of dMap) {
    if (!mMap.has(key)) {
        dItems.forEach(item => {
            console.log(`  🔴 [${item.menu}] "${item.text}" → ${item.href}`);
            mismatches.push({ type: 'Missing from Mobile', menu: item.menu, text: item.text, href: item.href });
        });
        missingCount++;
        totalMismatches++;
    }
}
if (missingCount === 0) console.log('  ✅ কোনো item missing নেই');

// B. Items in Mobile but NOT in Desktop
console.log('\n\n📋 B. Items in MOBILE but MISSING from DESKTOP');
console.log('-'.repeat(50));
missingCount = 0;
for (const [key, mItems] of mMap) {
    if (!dMap.has(key)) {
        mItems.forEach(item => {
            console.log(`  🔴 [${item.menu}] "${item.text}" → ${item.href}`);
            mismatches.push({ type: 'Missing from Desktop', menu: item.menu, text: item.text, href: item.href });
        });
        missingCount++;
        totalMismatches++;
    }
}
if (missingCount === 0) console.log('  ✅ কোনো item missing নেই');

// C. Items with same name but different links
console.log('\n\n📋 C. Items with SAME NAME but DIFFERENT LINK');
console.log('-'.repeat(50));
let linkDiffCount = 0;
for (const [key, dItems] of dMap) {
    if (mMap.has(key)) {
        const mItems = mMap.get(key);
        // Compare href sets
        const dHrefs = [...new Set(dItems.map(i => i.href))].sort();
        const mHrefs = [...new Set(mItems.map(i => i.href))].sort();
        
        if (dHrefs.join('|') !== mHrefs.join('|')) {
            console.log(`  🔴 "${dItems[0].text}" [${dItems[0].menu}]`);
            console.log(`     Desktop link: ${dHrefs.join(', ')}`);
            console.log(`     Mobile link:  ${mHrefs.join(', ')}`);
            mismatches.push({
                type: 'Link Mismatch',
                menu: dItems[0].menu,
                text: dItems[0].text,
                desktopHref: dHrefs.join(', '),
                mobileHref: mHrefs.join(', ')
            });
            linkDiffCount++;
            totalMismatches++;
        }
    }
}
if (linkDiffCount === 0) console.log('  ✅ সব item-এর link একই');

// ============================
// PRINT ALL ITEMS FOR VERIFICATION
// ============================
console.log('\n\n📋 D. FULL ITEM LIST — Desktop');
console.log('-'.repeat(50));
let currentMenu = '';
desktopItems.forEach((item, idx) => {
    if (item.menu !== currentMenu) {
        currentMenu = item.menu;
        console.log(`\n  [${currentMenu}]`);
    }
    console.log(`    ${idx+1}. "${item.text}" → ${item.href}`);
});

console.log('\n\n📋 E. FULL ITEM LIST — Mobile');
console.log('-'.repeat(50));
currentMenu = '';
mobileItems.forEach((item, idx) => {
    if (item.menu !== currentMenu) {
        currentMenu = item.menu;
        console.log(`\n  [${currentMenu}]`);
    }
    console.log(`    ${idx+1}. "${item.text}" → ${item.href}`);
});

// ============================
// SUMMARY
// ============================
console.log('\n\n' + '='.repeat(60));
console.log(`  TOTAL MISMATCHES: ${totalMismatches}`);
console.log('='.repeat(60));
if (mismatches.length > 0) {
    console.log('\n  MISMATCH DETAILS:');
    mismatches.forEach((m, i) => {
        console.log(`  ${i+1}. [${m.type}] [${m.menu}] "${m.text}"`);
        if (m.desktopHref) console.log(`     Desktop: ${m.desktopHref}`);
        if (m.mobileHref) console.log(`     Mobile:  ${m.mobileHref}`);
        if (m.href) console.log(`     Link: ${m.href}`);
    });
} else {
    console.log('\n  ✅ কোনো mismatch নেই! Desktop ও Mobile-এর সব menu items ও links হুবহু একই।');
}

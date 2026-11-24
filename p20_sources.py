"""Migrate old default sources to Google Fonts without deleting custom entries."""
GOOGLE={'id':'googlefonts','name':'Google Fonts','country':'INT','url':'https://fonts.google.com/','enabled':True}
OLD_IDS={'vietfont','fontviethoa','fontchuvietcom','taifontviethoa','fontchuvietvn','svnfont','onimine','sjfont','adina','phamkhoi','myfonts','fontsquirrel'}
def migrate_sources(rows):
    out=[dict(GOOGLE)]
    for r in rows:
        if r.get('id')=='googlefonts':continue
        if r.get('id') in OLD_IDS:continue
        out.append(dict(r))
    return out

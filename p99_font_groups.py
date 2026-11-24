"""P99: group font collections of at least 21 distinct files, preserving source files."""
import os,re,shutil,collections,time,logging
from pathlib import Path
from p98_font_warehouse import EXTS,unique_path,within

KNOWN=('UTM','SVN','VNI','UVN','HL','iCiel','FS','DFVN','MTO','Google Fonts')
def collection(path):
    name=os.path.splitext(os.path.basename(path))[0].strip()
    # Prefer explicit collection prefixes, never infer unrelated font families as one pack.
    for prefix in KNOWN:
        if re.match(r'^'+re.escape(prefix)+r'(?=$|[\s._-]|[A-Z][a-z])',name,re.I):return prefix
    try:
        from fontTools.ttLib import TTFont
        f=TTFont(path,lazy=True)
        try:
            names=f['name'].names
            def get(n):
                for record in names:
                    if record.nameID==n:
                        try:return record.toUnicode()
                        except Exception:pass
                return ''
            family=get(16) or get(1)
            # A single family is not necessarily a large font collection.
            return family.strip() if family.strip() else None
        finally:f.close()
    except Exception:return None

class FastNameAllocator:
    """One directory listing per destination, case-insensitive Windows name reservation."""
    def __init__(self):
        self.used={}
        self.next_suffix={}
    def reserve(self,folder,name):
        folder=os.path.normcase(os.path.abspath(folder))
        if folder not in self.used:
            self.used[folder]={n.casefold() for n in os.listdir(folder)}
        used=self.used[folder]
        base,ext=os.path.splitext(name)
        if name.casefold() not in used:
            used.add(name.casefold());return os.path.join(folder,name)
        key=(folder,name.casefold());i=self.next_suffix.get(key,2)
        while True:
            candidate=f'{base} ({i}){ext}'
            if candidate.casefold() not in used:
                used.add(candidate.casefold());self.next_suffix[key]=i+1
                return os.path.join(folder,candidate)
            i+=1

def organize(destination,threshold=21,report=None,progress=None):
    dest=os.path.realpath(destination)
    files=[]
    for root,dirs,names in os.walk(dest):
        dirs[:]=[d for d in dirs if not d.startswith('_') and not os.path.islink(os.path.join(root,d))]
        for name in names:
            p=os.path.join(root,name)
            if os.path.splitext(name)[1].lower() in EXTS and not os.path.islink(p):files.append(p)
    groups=collections.defaultdict(list)
    total=max(1,len(files))
    for i,p in enumerate(files,1):
        label=collection(p)
        groups[label].append(p)
        if progress and (i%25==0 or i==len(files)):
            progress('Đang đọc tên và họ font',i,total,p)
    eligible={k for k,v in groups.items() if k and len(v)>=threshold}
    stats={'grouped':0,'loose':0,'collections':len(eligible),'errors':[],'slow_operations':[]}
    allocator=FastNameAllocator()
    log_path=os.path.join(dest,'_P117_PERFORMANCE.log')
    moved_count=0
    with open(log_path,'a',encoding='utf-8') as log:
        log.write('\nP117 start '+time.strftime('%Y-%m-%d %H:%M:%S')+'; files='+str(len(files))+'\n')
        for key,paths in groups.items():
            folder=key if key in eligible else 'FONT RỜI RẠC'
            folder=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',folder).strip(' .')[:90] or 'FONT RỜI RẠC'
            target_dir=os.path.join(dest,folder)
            try:os.makedirs(target_dir,exist_ok=True)
            except OSError as exc:
                stats['errors'].append(f'{target_dir}: {exc}');continue
            for p in paths:
                moved_count+=1
                # Report the *last completed* operation, not the next pending file.
                t0=time.monotonic()
                if os.path.normcase(os.path.abspath(os.path.dirname(p)))==os.path.normcase(os.path.abspath(target_dir)):
                    if progress and (moved_count%10==0 or moved_count==len(files)):
                        progress('Đang sắp xếp font vào thư mục',moved_count,total,p)
                    continue
                try:
                    target=allocator.reserve(target_dir,os.path.basename(p))
                    # Destination is always a subfolder of the same warehouse root.
                    # os.rename avoids copy-and-delete overhead of shutil.move.
                    os.rename(p,target)
                    stats['grouped' if key in eligible else 'loose']+=1
                except OSError as exc:
                    stats['errors'].append(f'{p}: {exc}')
                    log.write(f'ERROR {p}: {exc}\n');log.flush()
                finally:
                    elapsed=time.monotonic()-t0
                    if elapsed>=2:
                        stats['slow_operations'].append({'file':p,'seconds':round(elapsed,2)})
                        log.write(f'SLOW_MOVE {elapsed:.2f}s {p}\n');log.flush()
                    if progress and (moved_count%10==0 or moved_count==len(files)):
                        progress('Đang sắp xếp font vào thư mục',moved_count,total,p)
        log.write('P117 end '+time.strftime('%Y-%m-%d %H:%M:%S')+'; errors='+str(len(stats['errors']))+'\n')
    if report:report('Phân loại: %d bộ từ %d font, %d font vào bộ, %d font rời.'%(stats['collections'],threshold,stats['grouped'],stats['loose']))
    return stats

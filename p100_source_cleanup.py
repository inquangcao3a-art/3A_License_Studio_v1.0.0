"""P100: explicit, verified, reversible source font cleanup (Recycle Bin only)."""
import os
from p98_font_warehouse import EXTS, digest, within

def preview(sources, destination, progress=None, verified_hashes=None):
    """Return source font paths whose bytes exist in destination; never include system fonts."""
    dest=os.path.realpath(destination)
    hashes=set(verified_hashes) if verified_hashes is not None else set()
    if verified_hashes is None and progress:progress("Đang xác minh bản sao trong kho",0,1)
    if verified_hashes is None:
      for root,dirs,names in os.walk(dest):
          dirs[:]=[d for d in dirs if not d.startswith('_') and not os.path.islink(os.path.join(root,d))]
          for name in names:
            path=os.path.join(root,name)
            if os.path.splitext(name)[1].lower() in EXTS and not os.path.islink(path):
                try: hashes.add((os.path.getsize(path),digest(path)))
                except OSError: pass
    safe=[]; skipped=[]
    if progress:progress("Đang xác minh bản sao font nguồn",0,1)
    source_files=[]
    windir=os.path.realpath(os.environ.get('WINDIR',r'C:\Windows'))
    for source in sources:
        src=os.path.realpath(source)
        if within(src,windir) or within(windir,src) or within(src,dest) or within(dest,src):
            skipped.append((src,'Thư mục hệ thống hoặc đường dẫn chồng lấn'));continue
        for root,dirs,names in os.walk(src):
            dirs[:]=[d for d in dirs if not os.path.islink(os.path.join(root,d))]
            for name in names:
                path=os.path.join(root,name)
                if os.path.splitext(name)[1].lower() not in EXTS or os.path.islink(path):continue
                source_files.append(path)
    total=max(1,len(source_files))
    for i,path in enumerate(source_files,1):
        try:
            size=os.path.getsize(path);sha=digest(path)
            if (size,sha) in hashes:safe.append((path,size,sha))
            else:skipped.append((path,'Không tìm thấy bản sao trùng khớp trong kho'))
        except OSError as exc:skipped.append((path,str(exc)))
        if progress and (i%25==0 or i==len(source_files)):
            progress("Đang xác minh bản sao font nguồn",i,total,path)
    return safe,skipped

def recycle_verified(candidates,destination):
    """Revalidate immediately before recycle; fail closed if send2trash unavailable."""
    try:from send2trash import send2trash
    except ImportError as exc:raise RuntimeError('Thiếu thư viện send2trash. Chạy: pip install send2trash. Không xóa bất kỳ tệp nào.') from exc
    # Scan each distinct parent once; never rescan the same directory thousands of times.
    parents=sorted({os.path.dirname(p) for p,_,_ in candidates})
    safe_now,_=preview(parents,destination)
    verified={(p,size,sha) for p,size,sha in safe_now}
    moved=[];errors=[]
    for item in candidates:
        if item not in verified:
            errors.append('%s: Dữ liệu đã thay đổi hoặc không còn bản sao hợp lệ'%item[0]);continue
        try:send2trash(item[0]);moved.append(item[0])
        except Exception as exc:errors.append('%s: %s'%(item[0],exc))
    return moved,errors

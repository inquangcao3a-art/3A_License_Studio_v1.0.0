"""P98: safe font warehouse: SHA-256 exact deduplication and reversible quarantine."""
import os, hashlib, shutil, json, datetime, threading, queue, time, tkinter as tk
from tkinter import ttk, filedialog, messagebox
EXTS={'.ttf','.otf','.ttc','.otc'}

def within(path, folder):
    try:return os.path.commonpath([os.path.normcase(os.path.realpath(path)),os.path.normcase(os.path.realpath(folder))])==os.path.normcase(os.path.realpath(folder))
    except ValueError:return False

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def unique_path(folder,name):
    base,ext=os.path.splitext(name);p=os.path.join(folder,name);i=2
    while os.path.lexists(p):p=os.path.join(folder,'%s (%s)%s'%(base,i,ext));i+=1
    return p

def consolidate(sources,destination,report=None,progress=None):
    """Copy from source; quarantine exact duplicate existing destination files; never touch source."""
    dest=os.path.realpath(destination);os.makedirs(dest,exist_ok=True)
    quarantine=os.path.join(dest,'_FONT_TRUNG_CACH_LY')
    os.makedirs(quarantine,exist_ok=True)
    stats={'existing':0,'copied':0,'duplicates_skipped':0,'quarantined':0,'errors':[], 'quarantine':quarantine}
    hashes={};manifest=[]
    def emit(stage, done, total, detail=''):
        if progress:progress(stage,done,total,detail)
    # Precount work units; never report 100% until grouping has completed.
    existing_files=[];source_files=[]
    for root,dirs,files in os.walk(dest):
        dirs[:]=[d for d in dirs if not within(os.path.join(root,d),quarantine) and not os.path.islink(os.path.join(root,d))]
        existing_files.extend(os.path.join(root,n) for n in files if os.path.splitext(n)[1].lower() in EXTS and not os.path.islink(os.path.join(root,n)))
    for source in sources:
        src=os.path.realpath(source)
        if not os.path.isdir(src) or within(dest,src) or within(src,dest):continue
        for root,dirs,files in os.walk(src):
            dirs[:]=[d for d in dirs if not os.path.islink(os.path.join(root,d))]
            source_files.extend(os.path.join(root,n) for n in files if os.path.splitext(n)[1].lower() in EXTS and not os.path.islink(os.path.join(root,n)))
    total=max(1,len(existing_files)+len(source_files));done=0
    emit('Đang kiểm tra font',0,total)

    def log(s):
        if report:report(s)
    # Existing warehouse files are canonical in deterministic alphabetical order.
    for root,dirs,files in os.walk(dest):
        dirs[:]=sorted(d for d in dirs if not within(os.path.join(root,d),quarantine) and not os.path.islink(os.path.join(root,d)))
        for name in sorted(files):
            p=os.path.join(root,name)
            if os.path.splitext(name)[1].lower() not in EXTS or os.path.islink(p):continue
            done+=1;emit('Đang kiểm tra font trong kho',done,total,name)
            try:
                key=(os.path.getsize(p),digest(p))
                if key in hashes:
                    os.makedirs(quarantine,exist_ok=True)
                    target=unique_path(quarantine,name)
                    shutil.move(p,target)
                    manifest.append({'duplicate':p,'kept':hashes[key],'quarantined':target,'sha256':key[1]})
                    stats['quarantined']+=1
                else:hashes[key]=p;stats['existing']+=1
            except (OSError,PermissionError) as exc:stats['errors'].append('%s: %s'%(p,exc))
    for source in sources:
        src=os.path.realpath(source)
        if not os.path.isdir(src):stats['errors'].append('Thư mục không tồn tại: '+src);continue
        if within(dest,src) or within(src,dest):
            stats['errors'].append('Bỏ qua thư mục nguồn trùng/lồng kho: '+src);continue
        for root,dirs,files in os.walk(src):
            dirs[:]=sorted(d for d in dirs if not os.path.islink(os.path.join(root,d)))
            for name in sorted(files):
                p=os.path.join(root,name)
                if os.path.splitext(name)[1].lower() not in EXTS or os.path.islink(p):continue
                done+=1;emit('Đang gom và lọc trùng',done,total,name)
                try:
                    key=(os.path.getsize(p),digest(p))
                    if key in hashes:stats['duplicates_skipped']+=1;continue
                    target=unique_path(dest,name)
                    tmp=target+'.partial'
                    try:
                        with open(p,'rb') as fi,open(tmp,'xb') as fo:shutil.copyfileobj(fi,fo,1024*1024)
                        if (os.path.getsize(tmp),digest(tmp))!=key:raise IOError('Dữ liệu sao chép không khớp')
                        os.replace(tmp,target)
                    finally:
                        if os.path.exists(tmp):os.remove(tmp)
                    hashes[key]=target;stats['copied']+=1
                except (OSError,PermissionError) as exc:stats['errors'].append('%s: %s'%(p,exc))
    if manifest:
        filename=os.path.join(quarantine,'bao_cao_trung_%s.json'%datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        with open(filename,'w',encoding='utf-8') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
    from p99_font_groups import organize
    emit('Đang phân loại bộ font',total,total,'Đang sắp xếp UTM, SVN, VNI...')
    stats['organization']=organize(dest,21,report,progress=emit)
    # Reuse verified content hashes instead of rehashing the entire destination.
    # Only use this cache if no file operations failed.
    if not stats['errors'] and not stats['organization'].get('errors'):
        stats['_verified_hashes']=set(hashes.keys())
    if not stats['errors'] and not stats['organization'].get('errors'):
        emit('Hoàn tất',total,total)
    else:
        emit('Có lỗi cần kiểm tra',total,total)
    log('Hoàn tất: %s font có sẵn, %s font mới, %s bản trùng bỏ qua, %s font cách ly, %s lỗi.'%(stats['existing'],stats['copied'],stats['duplicates_skipped'],stats['quarantined'],len(stats['errors'])))
    return stats

def choose_source_cleanup(parent, eligible_count, retained_count):
    """Explicit, accessible choice; closing dialog always means KEEP."""
    choice={'value':False}
    dlg=tk.Toplevel(parent)
    dlg.title('XÁC NHẬN XỬ LÝ FONT NGUỒN')
    dlg.configure(bg='#171c26')
    dlg.geometry('630x360')
    dlg.minsize(610,350)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(True,True)
    body=tk.Frame(dlg,bg='#171c26',padx=25,pady=20)
    body.pack(fill='both',expand=True)
    tk.Label(body,text='ĐÃ GOM VÀ PHÂN LOẠI FONT THÀNH CÔNG',bg='#171c26',fg='#f1c16b',font=('Segoe UI',17,'bold'),wraplength=620).pack(anchor='w',pady=(0,14))
    tk.Label(body,text=f'{eligible_count:,} FONT NGUỒN ĐÃ CÓ BẢN SAO ĐƯỢC KIỂM TRA',bg='#171c26',fg='white',font=('Segoe UI',14,'bold'),wraplength=620).pack(anchor='w',pady=(0,8))
    tk.Label(body,text=f'{retained_count:,} tệp chưa đủ điều kiện sẽ luôn được GIỮ LẠI.',bg='#171c26',fg='#d4d9e3',font=('Segoe UI',12),wraplength=620).pack(anchor='w')
    tk.Label(body,text='Bạn muốn xử lý các font nguồn đã có bản sao như thế nào?',bg='#171c26',fg='white',font=('Segoe UI',12,'bold'),wraplength=620).pack(anchor='w',pady=(18,9))
    buttons=tk.Frame(body,bg='#171c26');buttons.pack(fill='x',pady=(0,12))
    def finish(move):
        choice['value']=move
        dlg.destroy()
    keep=tk.Button(buttons,text='GIỮ LẠI FONT NGUỒN',command=lambda:finish(False),bg='#27644a',fg='white',activebackground='#347e5d',activeforeground='white',font=('Segoe UI',12,'bold'),height=2,relief='flat',cursor='hand2')
    keep.pack(side='left',fill='x',expand=True,padx=(0,7))
    recycle=tk.Button(buttons,text='CHUYỂN VÀO THÙNG RÁC',command=lambda:finish(True),bg='#a53c41',fg='white',activebackground='#c54b52',activeforeground='white',font=('Segoe UI',12,'bold'),height=2,relief='flat',cursor='hand2')
    recycle.pack(side='left',fill='x',expand=True,padx=(7,0))
    tk.Label(body,text='Chỉ chuyển font nguồn đã xác thực. Không xóa thư mục nguồn. Có thể khôi phục từ Thùng rác Windows.',bg='#171c26',fg='#cbd2df',font=('Segoe UI',10),wraplength=620,justify='left').pack(anchor='w')
    dlg.protocol('WM_DELETE_WINDOW',lambda:finish(False))
    dlg.bind('<Escape>',lambda event:finish(False))
    dlg.bind('<Return>',lambda event:finish(False))
    dlg.after(30,lambda:keep.focus_set() if dlg.winfo_exists() else None)
    parent.wait_window(dlg)
    return choice['value']

def ask_register_warehouse(parent):
    """Default to not registering; explicit Vietnamese action labels."""
    answer={'yes':False}
    dlg=tk.Toplevel(parent)
    dlg.title('ĐĂNG KÝ KHO FONT VÀO THƯ VIỆN')
    dlg.geometry('610x230');dlg.minsize(580,210)
    dlg.configure(bg='#171c26');dlg.transient(parent);dlg.grab_set()
    tk.Label(dlg,text='ĐĂNG KÝ KHO FONT ĐỂ TÌM KIẾM VÀ HỌC FONT?',bg='#171c26',fg='#f1c16b',font=('Segoe UI',15,'bold'),wraplength=580).pack(padx=18,pady=(22,12))
    tk.Label(dlg,text='Kho font đã gom sẽ được thêm vào danh sách thư viện của AI Font Finder PRO.',bg='#171c26',fg='white',font=('Segoe UI',11),wraplength=580).pack(padx=18)
    row=tk.Frame(dlg,bg='#171c26');row.pack(fill='x',padx=20,pady=25)
    def close(yes):answer['yes']=yes;dlg.destroy()
    tk.Button(row,text='KHÔNG ĐĂNG KÝ',command=lambda:close(False),font=('Segoe UI',12,'bold'),bg='#454c59',fg='white',height=2).pack(side='left',expand=True,fill='x',padx=5)
    tk.Button(row,text='ĐĂNG KÝ KHO FONT',command=lambda:close(True),font=('Segoe UI',12,'bold'),bg='#27644a',fg='white',height=2).pack(side='left',expand=True,fill='x',padx=5)
    dlg.protocol('WM_DELETE_WINDOW',lambda:close(False));dlg.bind('<Escape>',lambda e:close(False))
    parent.wait_window(dlg)
    return answer['yes']

def open_warehouse(parent,registered,register_callback):
    win=tk.Toplevel(parent);win.title('KHO FONT DỮ LIỆU — BUSINESS PRO');win.geometry('750x650');win.minsize(680,590)
    outer=ttk.Frame(win,padding=16);outer.pack(fill='both',expand=True)
    ttk.Label(outer,text='KHO FONT DỮ LIỆU',font=('Segoe UI',17,'bold')).pack(anchor='w')
    ttk.Label(outer,text='Gom font, lọc trùng và phân loại bộ từ 21 font. Sau khi hoàn tất, chọn GIỮ hoặc CHUYỂN FONT NGUỒN VÀO THÙNG RÁC.',wraplength=680).pack(anchor='w',pady=(4,12))
    ttk.Label(outer,text='THƯ MỤC NGUỒN').pack(anchor='w')
    frame=ttk.Frame(outer);frame.pack(fill='both',expand=True)
    listing=tk.Listbox(frame,selectmode='extended',height=7);listing.pack(side='left',fill='both',expand=True)
    sc=ttk.Scrollbar(frame,command=listing.yview);sc.pack(side='right',fill='y');listing.config(yscrollcommand=sc.set)
    for p in registered:
        if os.path.isdir(p):listing.insert('end',p)
    def add():
        p=filedialog.askdirectory(parent=win,title='Chọn thư mục font nguồn')
        if p and p not in listing.get(0,'end'):listing.insert('end',p)
    def remove():
        for i in reversed(listing.curselection()):listing.delete(i)
    actions=ttk.Frame(outer);actions.pack(fill='x',pady=6)
    ttk.Button(actions,text='+ THÊM THƯ MỤC',command=add).pack(side='left')
    ttk.Button(actions,text='BỎ KHỎI DANH SÁCH',command=remove).pack(side='left',padx=6)
    ttk.Label(outer,text='THƯ MỤC ĐÍCH').pack(anchor='w',pady=(6,0))
    dest=tk.StringVar(value=os.path.join(os.path.expanduser('~'),'Documents','KHO FONT DỮ LIỆU'))
    dr=ttk.Frame(outer);dr.pack(fill='x',pady=5)
    ttk.Entry(dr,textvariable=dest).pack(side='left',fill='x',expand=True)
    def choose():
        p=filedialog.askdirectory(parent=win,title='Chọn nơi đặt KHO FONT DỮ LIỆU')
        if p:dest.set(os.path.join(p,'KHO FONT DỮ LIỆU'))
    ttk.Button(dr,text='CHỌN VỊ TRÍ',command=choose).pack(side='left',padx=5)
    status=tk.StringVar(value='Sẵn sàng. Các tệp nguồn sẽ được giữ nguyên.')
    ttk.Label(outer,textvariable=status,wraplength=670).pack(anchor='w',pady=8)
    progress_value=tk.DoubleVar(value=0)
    progress_label=tk.StringVar(value='TIẾN ĐỘ: 0% · Chưa bắt đầu')
    ttk.Label(outer,textvariable=progress_label).pack(anchor='w',pady=(5,2))
    bar=ttk.Progressbar(outer,variable=progress_value,maximum=100,mode='determinate')
    bar.pack(fill='x',ipady=5,pady=(0,8))
    # P114: live operation monitor, independent of search-mode monitor.
    monitor=ttk.LabelFrame(outer,text='HIỂN THỊ CHUYỂN ĐỘNG KHO FONT')
    monitor.pack(fill='x',pady=(0,6))
    monitor_stage=tk.StringVar(value='SẴN SÀNG · Chưa có tác vụ')
    monitor_detail=tk.StringVar(value='Chọn nguồn và nhấn GOM FONT để bắt đầu.')
    ttk.Label(monitor,textvariable=monitor_stage).pack(anchor='w',padx=8,pady=(4,0))
    ttk.Label(monitor,textvariable=monitor_detail,wraplength=630).pack(anchor='w',padx=8,pady=(0,5))
    # P116: real worker events, latest three font names, newest at top.
    font_rows=[]
    for _ in range(3):
        row=tk.StringVar(value='—')
        ttk.Label(monitor,textvariable=row,font=('Segoe UI',10)).pack(anchor='w',padx=10,pady=1)
        font_rows.append(row)
    last_font=[None]
    runbtn=ttk.Button(outer,text='GOM FONT · LỌC TRÙNG · PHÂN LOẠI BỘ');runbtn.pack(fill='x',pady=6)
    def completion_dialog(result, eligible, retained, on_choice):
        """One nonblocking result window: celebration and safe cleanup decision."""
        import random
        from p90_audio_backend import play_wav
        from p101_completion_audio import WAV_BYTES
        play_wav(WAV_BYTES,'P110 - Kho font hoan tat',on_result=lambda ok,msg: (win.after(0,lambda:status.set('Lỗi âm thanh: '+msg)) if not ok and win.winfo_exists() else None))
        dlg=tk.Toplevel(win);dlg.title('KHO FONT DỮ LIỆU · HOÀN THÀNH');dlg.geometry('670x460');dlg.minsize(630,420)
        dlg.configure(bg='#171c26');dlg.transient(win);dlg.grab_set()
        body=tk.Frame(dlg,bg='#171c26',padx=22,pady=15);body.pack(fill='both',expand=True)
        tk.Label(body,text='CHÚC MỪNG! ĐÃ GOM VÀ PHÂN LOẠI FONT',font=('Segoe UI',17,'bold'),fg='#f1c16b',bg='#171c26').pack(anchor='w')
        tk.Label(body,text='Font mới: {:,}  |  Bỏ qua trùng: {:,}  |  Cách ly: {:,}'.format(result['copied'],result['duplicates_skipped'],result['quarantined']),font=('Segoe UI',11),fg='white',bg='#171c26').pack(anchor='w',pady=(7,2))
        tk.Label(body,text='{:,.0f} font nguồn đã xác minh có bản sao · {:,.0f} tệp sẽ giữ lại'.format(eligible,retained),font=('Segoe UI',11,'bold'),fg='#cbd2df',bg='#171c26').pack(anchor='w')
        canvas=tk.Canvas(body,height=110,bg='#171c26',highlightthickness=0);canvas.pack(fill='x',pady=(5,5))
        rng=random.Random();colors=['#f1c16b','#f36c7b','#74d9f6','#9bf7a1','#cf98ff'];parts=[]
        for _ in range(65):
            x=rng.randint(10,620);y=rng.randint(5,100)
            parts.append((canvas.create_oval(x,y,x+4,y+4,fill=rng.choice(colors),outline=''),rng.uniform(-1.5,1.5),rng.uniform(-1,1)))
        frames=[0]
        def animate():
            if not dlg.winfo_exists() or frames[0]>=45:return
            for item,vx,vy in parts:canvas.move(item,vx,vy+frames[0]*.01)
            frames[0]+=1;dlg.after(45,animate)
        animate()
        tk.Label(body,text='Bạn muốn xử lý các font nguồn như thế nào?',font=('Segoe UI',13,'bold'),fg='white',bg='#171c26').pack(anchor='w',pady=(4,10))
        row=tk.Frame(body,bg='#171c26');row.pack(fill='x')
        finished=[False]
        def finish(move):
            if finished[0]:return
            finished[0]=True;dlg.destroy();win.after(0,lambda:on_choice(move))
        tk.Button(row,text='GIỮ LẠI FONT NGUỒN',command=lambda:finish(False),font=('Segoe UI',12,'bold'),bg='#27644a',fg='white',height=2,relief='flat').pack(side='left',fill='x',expand=True,padx=(0,7))
        tk.Button(row,text='CHUYỂN VÀO THÙNG RÁC',command=lambda:finish(True),font=('Segoe UI',12,'bold'),bg='#a53c41',fg='white',height=2,relief='flat',state='normal' if eligible else 'disabled').pack(side='left',fill='x',expand=True,padx=(7,0))
        tk.Label(body,text='Chỉ chuyển font đã xác minh. Đóng cửa sổ hoặc nhấn Esc = GIỮ LẠI. Có thể khôi phục từ Thùng rác Windows.',font=('Segoe UI',10),fg='#cbd2df',bg='#171c26',wraplength=650,justify='left').pack(anchor='w',pady=14)
        dlg.protocol('WM_DELETE_WINDOW',lambda:finish(False));dlg.bind('<Escape>',lambda e:finish(False));dlg.bind('<Return>',lambda e:finish(False))

    events=queue.Queue(maxsize=128);active=[False]
    pending_close_after_cleanup=[False]
    registered_after_completion=[False]
    def register_and_close(destination):
        # Register while the warehouse still exists; callback schedules training on the root.
        if not registered_after_completion[0]:
            try:
                register_callback(destination)
                registered_after_completion[0]=True
            except Exception as exc:
                messagebox.showerror('KHÔNG ĐĂNG KÝ ĐƯỢC KHO FONT',str(exc),parent=win)
                return False
        if win.winfo_exists():win.destroy()
        return True
    # Keep only the latest progress snapshot. A large font collection must not flood Tk's event loop.
    progress_lock=threading.Lock();latest_progress=[None]
    heartbeat=[time.monotonic()];started=[None];last_detail=[''];last_stage=['']
    def update_progress(stage,done,total,detail):
        percent=min(99,round(done/max(1,total)*95))
        if stage=='Đang phân loại bộ font':percent=95
        if stage=='Đang đọc tên và họ font':percent=95+round(done/max(1,total)*2)
        if stage=='Đang sắp xếp font vào thư mục':percent=97+round(done/max(1,total))
        if stage.startswith('Đang xác minh bản sao'):percent=98+round(done/max(1,total))
        if stage=='Hoàn tất':percent=99  # 100% only after cleanup verification and done event
        progress_value.set(percent)
        progress_label.set('TIẾN ĐỘ: %d%% · %s · %d/%d tệp'%(percent,stage,done,total))
        last_stage[0]=stage;last_detail[0]=os.path.basename(str(detail)) if detail else ''
        if last_detail[0] and last_detail[0]!=last_font[0] and os.path.splitext(last_detail[0])[1].lower() in EXTS:
            last_font[0]=last_detail[0]
            for j in (2,1):font_rows[j].set(font_rows[j-1].get())
            font_rows[0].set(last_detail[0])
        heartbeat[0]=time.monotonic()
        monitor_stage.set('%s  ·  %s/%s tệp'%(stage,done,total))
        monitor_detail.set('Đang xử lý: '+(last_detail[0] or 'Đang chuẩn bị...'))

    def poll():
        try:
            # Handle a bounded number of terminal events per GUI tick.
            for _ in range(8):
                try:kind,payload=events.get_nowait()
                except queue.Empty:break
                if kind=='progress':
                    stage,done,total,detail=payload
                    update_progress(stage,done,total,detail)
                    continue
                if kind=='done':
                    active[0]=False;runbtn.configure(state='normal')
                    monitor_stage.set('HOÀN THÀNH · Đang chờ xác nhận')
                    has_errors=bool(payload['errors'] or payload.get('organization',{}).get('errors'))
                    progress_value.set(100 if not has_errors else 99)
                    progress_label.set('TIẾN ĐỘ: '+('99% · Có lỗi cần kiểm tra' if has_errors else '100% · Đã hoàn thành'))
                    status.set('Đã gom %s font mới; bỏ qua %s bản trùng; cách ly %s bản trùng cũ; lỗi %s.'%(payload['copied'],payload['duplicates_skipped'],payload['quarantined'],len(payload['errors'])+len(payload.get('organization',{}).get('errors',[]))))
                    if has_errors:
                        all_errors=payload['errors']+payload.get('organization',{}).get('errors',[])
                        messagebox.showwarning('CẦN KIỂM TRA LỖI','Quá trình chưa hoàn tất an toàn. Không dọn font nguồn.\n\nSố lỗi: %d\n%s'%(len(all_errors),'\n'.join(all_errors[:5])),parent=win)
                    else:
                        candidates=payload.get('cleanup_candidates',[]);skipped=payload.get('cleanup_skipped',[])
                        def after_choice(move):
                            if move and candidates:
                                # Keep this window visible until all recycle operations succeed.
                                pending_close_after_cleanup[0]=True
                                status.set('Đang chuyển font đã xác minh vào Thùng rác...')
                                runbtn.configure(state='disabled');active[0]=True
                                def cleanup_worker():
                                    try:
                                        from p100_source_cleanup import recycle_verified
                                        moved,errors=recycle_verified(candidates,payload['destination'])
                                        events.put(('cleanup_done',(len(moved),errors,payload['destination'])))
                                    except Exception as exc:events.put(('cleanup_error',str(exc)))
                                threading.Thread(target=cleanup_worker,daemon=True).start()
                            else:
                                # GIỮ LẠI, Escape, or closing completion: close warehouse immediately.
                                register_and_close(payload['destination'])
                        completion_dialog(payload,len(candidates),len(skipped),after_choice)
                elif kind=='cleanup_done':
                    active[0]=False;runbtn.configure(state='normal')
                    count,errors,destination=payload
                    status.set('Đã chuyển %d font vào Thùng rác; %d lỗi.'%(count,len(errors)))
                    if errors:
                        pending_close_after_cleanup[0]=False
                        messagebox.showwarning('DỌN FONT CHƯA HOÀN TẤT','Đã chuyển %d font; còn %d lỗi. Cửa sổ được giữ mở để kiểm tra.\n\n%s'%(count,len(errors),'\n'.join(map(str,errors[:5]))),parent=win)
                    elif pending_close_after_cleanup[0]:
                        pending_close_after_cleanup[0]=False
                        register_and_close(destination)
                elif kind=='cleanup_error':
                    active[0]=False;runbtn.configure(state='normal');pending_close_after_cleanup[0]=False
                    messagebox.showerror('Không dọn font',str(payload),parent=win)
                else:active[0]=False;runbtn.configure(state='normal');messagebox.showerror('Lỗi kho font',str(payload),parent=win)
        except queue.Empty:pass
        # Coalesced progress: one UI update per tick, regardless of font count.
        with progress_lock:
            snapshot=latest_progress[0]
            latest_progress[0]=None
        if snapshot is not None and active[0]:
            stage,done,total,detail=snapshot
            update_progress(stage,done,total,detail)
        if active[0] and started[0] is not None:
            elapsed=int(time.monotonic()-started[0]);idle=int(time.monotonic()-heartbeat[0])
            if idle>=8:
                monitor_detail.set('CHƯA CÓ TIẾN ĐỘ %ds · Công đoạn: %s · Font gần nhất: %s · Tổng %ds. Xem _P117_PERFORMANCE.log'%(idle,last_stage[0],last_detail[0],elapsed))
            elif last_stage[0]:
                monitor_detail.set('Đang xử lý: %s · Đã chạy %ds'%(last_detail[0] or last_stage[0],elapsed))
        if win.winfo_exists():win.after(150,poll)
    def start():
        if active[0]:return
        src=list(listing.get(0,'end'));d=os.path.realpath(dest.get().strip())
        if not src or not d:messagebox.showwarning('Thiếu thông tin','Chọn ít nhất một thư mục nguồn và vị trí kho.',parent=win);return
        overlapping=[s for s in src if within(d,s) or within(s,d)]
        if overlapping:
            messagebox.showerror('THƯ MỤC NGUỒN KHÔNG HỢP LỆ','Bạn đang chọn chính KHO FONT DỮ LIỆU làm nguồn, hoặc hai thư mục lồng nhau.\n\nHãy bỏ khỏi THƯ MỤC NGUỒN:\n'+'\n'.join(overlapping[:5])+'\n\nKho đích sẽ được tự kiểm tra, không cần thêm vào danh sách nguồn.',parent=win)
            return
        if not messagebox.askyesno('Xác nhận','Sao chép font vào:\n%s\n\nFont nguồn giữ nguyên. Font trùng sẵn có trong kho sẽ chuyển vào thư mục cách ly. Tiếp tục?'%d,parent=win):return
        last_font[0]=None
        for row in font_rows:row.set('—')
        started[0]=time.monotonic();heartbeat[0]=started[0];last_stage[0]='Đang chuẩn bị';monitor_stage.set('Đang chuẩn bị');active[0]=True;runbtn.configure(state='disabled');progress_value.set(0);progress_label.set('TIẾN ĐỘ: 0% · Đang chuẩn bị');status.set('Đang quét và gom font. Vui lòng đợi...')
        def publish_progress(*args):
            with progress_lock:latest_progress[0]=args
        def worker():
            diag_path=os.path.join(d,'_P117_WORKFLOW.log')
            try:
                def timed_progress(stage,done,total,detail=''):
                    publish_progress(stage,done,total,detail)
                    # Sparse, durable stage checkpoints for diagnosing apparent freezes.
                    if stage!=timed_progress.previous or (done and done%500==0 and done!=timed_progress.last_count):
                        timed_progress.previous=stage;timed_progress.last_count=done
                        with open(diag_path,'a',encoding='utf-8') as fp:
                            fp.write('%s | %s | %s/%s | %s\n'%(time.strftime('%Y-%m-%d %H:%M:%S'),stage,done,total,detail))
                timed_progress.previous=None;timed_progress.last_count=-1
                result=consolidate(src,d,progress=timed_progress)
                result['sources']=src;result['destination']=d
                if not result['errors'] and not result.get('organization',{}).get('errors'):
                    from p100_source_cleanup import preview
                    timed_progress('Đang xác minh bản sao font nguồn',0,1)
                    result['cleanup_candidates'],result['cleanup_skipped']=preview(src,d,progress=timed_progress,verified_hashes=result.pop('_verified_hashes',None))
                with open(diag_path,'a',encoding='utf-8') as fp:fp.write('%s | WORKER_DONE\n'%time.strftime('%Y-%m-%d %H:%M:%S'))
                events.put(('done',result))
            except Exception as exc:
                import traceback
                try:
                    with open(diag_path,'a',encoding='utf-8') as fp:fp.write('%s | WORKER_ERROR | %s\n'%(time.strftime('%Y-%m-%d %H:%M:%S'),traceback.format_exc()))
                except OSError:pass
                events.put(('error',exc))
        threading.Thread(target=worker,daemon=True).start()
    runbtn.configure(command=start)
    win.after(150,poll)

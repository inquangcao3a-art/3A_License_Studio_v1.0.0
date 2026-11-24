"""Safe exit confirmation and lightweight animated 3A advertisement."""
import os,sys,tkinter as tk,random,math,threading,time
from p149_robot_images import ROBOT_IMAGES

BG='#151C27'; CARD='#202B3B'; GOLD='#FFC66B'; LIGHT='#F6F8FC'; MUTED='#B9C6D5'

def asset(name):
    """Locate robot resources in source, PyInstaller onedir/onefile, or installed folder."""
    module_dir = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        install_dir = os.path.dirname(os.path.abspath(sys.executable))
        bases = [getattr(sys, '_MEIPASS', None),
                 os.path.join(install_dir, '_internal'), install_dir]
    else:
        bases = [module_dir]
    tried=[]
    for base in bases:
        if not base: continue
        for candidate in (os.path.join(base, 'assets', name),
                          os.path.join(base, name)):
            tried.append(candidate)
            if os.path.isfile(candidate): return candidate
    raise FileNotFoundError('Robot asset missing: '+name+'; searched: '+' | '.join(tried))


def robot_photo(master, name):
    return tk.PhotoImage(master=master, data=ROBOT_IMAGES[name], format='png')


def confirm_close(root, version='P119', busy=False, serial='', activate_license=None):
    win=tk.Toplevel(root);win.title('XÁC NHẬN THOÁT — QUẢNG CÁO 3A');win.configure(bg=BG)
    win.resizable(False,False);win.transient(root)
    win.robot_icon = robot_photo(win, 'logo_64')
    win.iconphoto(False, win.robot_icon)
    result={'exit':False};state={'running':True,'frame':0,'job':None}
    def finish(leave=False):
        result['exit']=leave;state['running']=False
        for key in ('job','robot_job'):
            if state.get(key) is not None:
                try:win.after_cancel(state[key])
                except tk.TclError:pass
        win.destroy()
    win.protocol('WM_DELETE_WINDOW',finish)
    win.bind('<Escape>',lambda e:finish())
    win.bind('<Return>',lambda e:finish())
    top=tk.Frame(win,bg=CARD,padx=12,pady=9);top.pack(fill='x',padx=10,pady=(10,0))
    # The exit dialog loops the 12 turntable frames while it is visible.
    ROBOT_FRAME_MS=150
    spin_images = [robot_photo(win, f'frame_{i:02d}') for i in range(12)]
    robot_holder=tk.Frame(top,bg=CARD,width=240,height=240)
    robot_holder.pack(side='left',padx=(0,12))
    robot_holder.pack_propagate(False)
    robot_label=tk.Label(robot_holder,name='robot_animation',bg=CARD,bd=0)
    robot_label.pack(fill='both',expand=True)
    state['robot_job']=None
    state['robot_index']=0
    state['robot_epoch']=time.monotonic()
    def spin_robot():
        state['robot_job']=None
        if not state['running'] or not win.winfo_exists():
            return
        # A hidden/minimized window consumes no animation ticks.
        if not win.winfo_viewable():
            state['robot_epoch']=time.monotonic()
            state['robot_job']=win.after(250,spin_robot)
            return
        elapsed=(time.monotonic()-state['robot_epoch'])*1000.0
        step=int(elapsed//ROBOT_FRAME_MS)
        idx=step%len(spin_images)
        if idx!=state['robot_index']:
            robot_label.configure(image=spin_images[idx])
            state['robot_index']=idx
        remaining=ROBOT_FRAME_MS-(elapsed%ROBOT_FRAME_MS)
        state['robot_job']=win.after(max(12,int(remaining)),spin_robot)
    robot_label.configure(image=spin_images[0])
    spin_robot()
    info=tk.Frame(top,bg=CARD);info.pack(side='left',fill='both',expand=True)
    tk.Label(info,text='THIẾT KẾ IN ẤN QUẢNG CÁO 3A',bg=CARD,fg=GOLD,font=('Segoe UI',12,'bold'),anchor='w').pack(fill='x')
    for t in ('ĐT: 0987620727 - 0979400 417',
              'Chuyên: IN Quảng Cáo - Khắc Dấu - Laser Siêu Tốc - Biển hiệu',
              'Đc: 34 Kha Vạn Cân, KP. Bình Đường 2,',
              'Phường Dĩ An, TP. Hồ Chí Minh'):
        tk.Label(info,text=t,bg=CARD,fg=LIGHT,font=('Segoe UI',8),anchor='w').pack(fill='x',pady=2)
    offer_bg = '#102239'
    offer = tk.Frame(info, name='license_offer', bg=offer_bg, padx=14, pady=7,
                     highlightthickness=1, highlightbackground='#947141')
    offer.pack(fill='x', pady=(10, 0))
    tk.Label(offer, text='BẢN QUYỀN AI FONT FINDER PRO',
             bg=offer_bg, fg='#AEDFFF', font=('Segoe UI', 9, 'bold')).pack(anchor='w')
    price_row = tk.Frame(offer, bg=offer_bg)
    price_row.pack(fill='x')
    tk.Label(price_row, name='license_price', text='249.000 ₫', bg=offer_bg,
             fg='#FFDA87', font=('Segoe UI', 26, 'bold')).pack(side='left')
    tk.Label(price_row, text='Thanh toán một lần', bg=offer_bg, fg=LIGHT,
             font=('Segoe UI', 9)).pack(side='left', padx=(12, 0))
    tk.Label(offer, text='Dùng thử miễn phí 15 ngày',
             bg=offer_bg, fg='#AEDFFF', font=('Segoe UI', 9)).pack(anchor='w')
    tk.Label(offer, name='exit_contact', text='Zalo 0979400417 — Mr. AI', bg=offer_bg,
             fg='#FFDA87', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(8, 0))
    tk.Label(offer, text='Sao chép số seri và gửi kèm địa chỉ Gmail nhận key.',
             bg=offer_bg, fg=LIGHT, font=('Segoe UI', 9), wraplength=390,
             justify='left').pack(anchor='w', pady=(2, 5))
    serial_row = tk.Frame(offer, bg=offer_bg)
    serial_row.pack(fill='x')
    serial_box = tk.Entry(serial_row, name='exit_serial', readonlybackground='#182C46',
                          fg=LIGHT, relief='flat', font=('Consolas', 10), width=32)
    serial_box.insert(0, serial or 'Không đọc được số seri')
    serial_box.configure(state='readonly')
    serial_box.pack(side='left', fill='x', expand=True)
    feedback = tk.StringVar(master=win)

    def copy_serial():
        win.clipboard_clear()
        win.clipboard_append(serial)
        feedback.set('Đã sao chép số seri.')

    tk.Button(serial_row, text='Sao chép', command=copy_serial,
              state='normal' if serial else 'disabled').pack(side='right', padx=(6, 0))
    tk.Label(offer, text='Key nhận qua Gmail', bg=offer_bg, fg=LIGHT,
             font=('Segoe UI', 9)).pack(anchor='w', pady=(5, 0))
    key_row = tk.Frame(offer, bg=offer_bg)
    key_row.pack(fill='x')
    key_box = tk.Entry(key_row, name='exit_key', bg='#182C46', fg=LIGHT,
                       insertbackground=LIGHT, relief='flat', width=28)
    key_box.pack(side='left', fill='x', expand=True)

    def activate(event=None):
        try:
            activate_license(key_box.get())
        except ValueError as exc:
            feedback.set(str(exc))
        else:
            key_box.delete(0, 'end')
            feedback.set('Đã kích hoạt. Chọn Ở LẠI để tiếp tục.')
        return 'break'

    tk.Button(key_row, text='Kích hoạt', command=activate, bg='#85D9FF',
              fg='#122039', state='normal' if activate_license else 'disabled').pack(side='right', padx=(6, 0))
    if activate_license:
        key_box.bind('<Return>', activate)
    tk.Label(offer, textvariable=feedback, bg=offer_bg, fg='#AEDFFF', anchor='w',
             font=('Segoe UI', 9)).pack(fill='x', pady=(3, 0))
    canvas=tk.Canvas(win,height=55,bg=BG,highlightthickness=0);canvas.pack(fill='x',padx=10,pady=(2,1))
    # Lightweight confetti fireworks + animated applause (visual).
    rng=random.Random(119)
    sparks=[]
    for k in range(42):
        cx=145 if k<21 else 580
        cy=30
        angle=2*math.pi*(k%21)/21
        speed=0.8+0.65*(k%4)
        obj=canvas.create_oval(cx,cy,cx+4,cy+4,fill=['#FF9C48','#FFD47E','#4AC6C4','#75D0A5','#C6A2F2'][k%5],outline='')
        sparks.append((obj,cx,cy,math.cos(angle)*speed,math.sin(angle)*speed,k))
    applause=canvas.create_text(365,36,text='👏  ✨  👏',fill='#FFD47E',font=('Segoe UI Emoji',17,'bold'))
    colors=['#FF9C48','#FFD47E','#4AC6C4','#75D0A5','#C6A2F2']
    dots=[]
    for i in range(17):
        xx=28+i*42; yy=11+(i*7)%24
        obj=canvas.create_oval(xx,yy,xx+4,yy+4,fill=colors[i%len(colors)],outline='')
        dots.append((obj,xx,yy,i))
    def play_applause():
        if sys.platform != 'win32':return
        def worker():
            try:
                import winsound
                winsound.PlaySound(asset('3a_applause.wav'),winsound.SND_FILENAME)
            except (OSError,RuntimeError,AttributeError):pass
        threading.Thread(target=worker,daemon=True).start()
    play_applause()
    def animate():
        state['job']=None
        if not state['running'] or not win.winfo_exists():return
        if not win.winfo_viewable():
            state['job']=win.after(300,animate)
            return
        state['frame']+=1;f=state['frame']
        # A short, soft pulse on the border keeps the price text steady.
        if f <= 24:
            glow = (1 - math.cos(f * math.pi / 6)) / 2
            color = '#%02x%02x%02x' % (148 + int(97 * glow),
                                      113 + int(73 * glow),
                                      65 + int(43 * glow))
            offer.configure(highlightbackground=color, highlightcolor=color)
        # Decorative effects finish after 4.2 seconds; robot continues indefinitely.
        if f>35:
            canvas.itemconfigure(applause,text='✨')
            return
        # First ~2.5 seconds: expanding confetti; no permanent CPU-heavy effect.
        for obj,cx,cy,vx,vy,k in (sparks if f<=33 else ()):
            t=min(f,27)
            px=cx+vx*t*2.7
            py=cy+vy*t*1.15+0.025*t*t
            canvas.coords(obj,px,py,px+4,py+4)
            if f>32:canvas.itemconfigure(obj,state='hidden')
        canvas.itemconfigure(applause,text=('👏  ✨  👏' if f%12<6 else '✨  👏  ✨'))
        for obj,x,y,i in dots:
            dy=((f+i*5)%24)-12
            canvas.coords(obj,x,y+dy*.32,x+4,y+dy*.32)
        state['job']=win.after(120,animate)
    animate()
    tk.Label(win,text='BẠN MUỐN THOÁT CHƯƠNG TRÌNH?',bg=BG,fg=GOLD,font=('Segoe UI',14,'bold')).pack(pady=(2,6))
    tk.Label(win,text='AI Font Finder PRO đang sẵn sàng phục vụ bạn!',bg=BG,fg=LIGHT,font=('Segoe UI',10)).pack()
    tk.Label(win,text='Nếu vừa bấm nhầm dấu X, hãy chọn Ở LẠI để tiếp tục.',bg=BG,fg=MUTED,font=('Segoe UI',10)).pack(pady=(5,0))
    if busy:
        tk.Label(win,text='LƯU Ý: Đang có tác vụ xử lý. Thoát có thể làm gián đoạn công việc.',bg=BG,fg='#FFAE9B',font=('Segoe UI',9,'bold')).pack(pady=(5,0))
    bar=tk.Frame(win,bg=BG)
    bar.pack(pady=(10,8))
    btn_style=dict(font=('Segoe UI',10,'bold'),height=1,width=20,bd=0,cursor='hand2',padx=6,pady=5)
    tk.Button(bar,text='THOÁT CHƯƠNG TRÌNH',command=lambda:finish(True),bg='#913F49',fg='white',activebackground='#B34D5A',activeforeground='white',**btn_style).pack(side='left',padx=(0,7))
    stay=tk.Button(bar,text='✓  Ở LẠI · TIẾP TỤC',command=finish,bg='#236A51',fg='white',activebackground='#2D8768',activeforeground='white',**btn_style)
    stay.pack(side='left',padx=(7,0))
    tk.Label(win,text='3A  •  '+version+'  •  BUSINESS PRO',bg=BG,fg=MUTED,font=('Segoe UI',8)).pack(side='bottom',pady=(0,10))
    win.update_idletasks()
    width = max(740, win.winfo_reqwidth())
    height = win.winfo_reqheight() + 10
    x = min(max(0, root.winfo_rootx() + (root.winfo_width() - width) // 2),
            max(0, win.winfo_screenwidth() - width))
    y = min(max(0, root.winfo_rooty() + (root.winfo_height() - height) // 2),
            max(0, win.winfo_screenheight() - height))
    win.geometry(f'{width}x{height}+{x}+{y}')
    win.grab_set();stay.focus_set();root.wait_window(win)
    return result['exit']

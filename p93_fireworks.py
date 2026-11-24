"""P93 celebratory, nonblocking Tk notification, no external dependencies."""
import tkinter as tk
import math, random

def show(root, count, seconds, stopped_early=False):
    dlg=tk.Toplevel(root)
    dlg.title('AI FONT FINDER PRO P93 • CHÚC MỪNG')
    dlg.configure(bg='#151D31')
    dlg.resizable(False,False)
    dlg.transient(root)
    dlg.protocol('WM_DELETE_WINDOW',dlg.destroy)
    canvas=tk.Canvas(dlg,width=550,height=225,bg='#151D31',highlightthickness=0)
    canvas.pack()
    colors=['#FFCB43','#FF6C88','#48E8FF','#9B7AFF','#6CF5A7','#FF9045']
    particles=[]
    rng=random.Random()
    for cx,cy in [(92,80),(460,70),(270,45),(400,135),(145,155)]:
        for k in range(22):
            a=2*math.pi*k/22;speed=rng.uniform(1.6,4.2)
            particles.append([cx,cy,math.cos(a)*speed,math.sin(a)*speed,0,rng.choice(colors)])
    canvas.create_text(275,83,text='🎉  CHÚC MỪNG!  🎉',font=('Segoe UI',22,'bold'),fill='#FFFFFF')
    canvas.create_text(275,128,text='ĐÃ HOÀN THÀNH NHIỆM VỤ!',font=('Segoe UI',14,'bold'),fill='#FFE17B')
    canvas.create_text(275,167,text=('Đã chấp nhận kết quả tại ngưỡng' if stopped_early else 'Tìm kiếm font đã hoàn tất'),font=('Segoe UI',11),fill='#D6E8FF')
    canvas.create_text(275,194,text='Đã kiểm tra %s font  •  %.2f giây'%(count,seconds),font=('Segoe UI',10),fill='#C0CADB')
    tk.Button(dlg,text='✓  HOÀN THÀNH',command=dlg.destroy,font=('Segoe UI',11,'bold'),bg='#247F5C',fg='white',activebackground='#1A6849',activeforeground='white',relief='flat',cursor='hand2',width=22,pady=9).pack(pady=(4,16))
    dlg.update_idletasks()
    x=root.winfo_rootx()+max(0,(root.winfo_width()-dlg.winfo_width())//2)
    y=root.winfo_rooty()+max(0,(root.winfo_height()-dlg.winfo_height())//2)
    dlg.geometry('+%d+%d'%(x,y))
    frame=[0]
    def animate():
        if not dlg.winfo_exists():return
        canvas.delete('spark')
        frame[0]+=1
        for p in particles:
            if p[4]>48:
                p[0],p[1],p[4]=rng.choice([90,260,460]),rng.choice([50,110,155]),0
            p[0]+=p[2];p[1]+=p[3];p[3]+=.035;p[4]+=1
            r=2.8*(1-p[4]/55)
            if r>0:canvas.create_oval(p[0]-r,p[1]-r,p[0]+r,p[1]+r,fill=p[5],outline='',tags='spark')
        if frame[0]<115:dlg.after(35,animate)
    animate()
    return dlg

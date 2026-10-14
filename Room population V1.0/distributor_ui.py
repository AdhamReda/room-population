"""Simple settings dialog for the Room Fixture Distributor (CPython / pythonnet)."""
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Windows.Forms import (
    Form, GroupBox, RadioButton, Button, CheckedListBox,
    DialogResult, FormBorderStyle, FormStartPosition, CheckBox
)
from System.Drawing import Point, Size


def _radio(text, y, checked=False):
    rb = RadioButton()
    rb.Text = text
    rb.Location = Point(12, y)
    rb.Size = Size(290, 22)
    rb.Checked = checked
    return rb


def _button(text, x, result, y=160):
    btn = Button()
    btn.Text = text
    btn.Location = Point(x, y)
    btn.Size = Size(75, 28)
    btn.DialogResult = result  
    return btn

def _checkbox(x,y,text="CheckBox",checked=True):
    chk=CheckBox()
    chk.Text =text
    chk.Location = Point(x, y)
    chk.Size = Size(310, 22)
    chk.Checked=checked
    return chk

def show_settings_dialog():
    """Returns {"mode": str, "diagnostic": bool}, or None if cancelled."""
    form = Form()
    form.Text = "Room Fixture Distributor"
    form.ClientSize = Size(340, 200)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.TopMost = True

    group = GroupBox()
    group.Text = "Target room selection"
    group.Location = Point(12, 12)
    group.Size = Size(316, 100)

    rb_auto = _radio("Automatic (match by name)", 22, checked=True)
    rb_except = _radio("Automatic, except... (exclude rooms)", 46)
    rb_manual = _radio("Manual (pick rooms)", 70)
    for rb in (rb_auto, rb_except, rb_manual):
        group.Controls.Add(rb)

    btn_run = _button("Run", 172, DialogResult.OK)
    btn_cancel = _button("Cancel", 253, DialogResult.Cancel)
    transfer_chckbx=_checkbox(12,100)
    for c in (group, btn_run, btn_cancel):
        form.Controls.Add(c)
    transfer_chckbx=_checkbox(12,120,text="Transfer Parameters")
    form.Controls.Add(transfer_chckbx)

    form.AcceptButton = btn_run
    form.CancelButton = btn_cancel

    if form.ShowDialog() != DialogResult.OK:
        return None

    if rb_except.Checked:
        mode = "automatic_except"
    elif rb_manual.Checked:
        mode = "manual"
    else:
        mode = "automatic"

    return {"mode": mode, "diagnostic": False, "parameters": transfer_chckbx.Checked}


def show_level_dialog(level_names):
    """Checklist of levels (all checked by default).
    Returns the list of checked level names, or None if cancelled."""
    form = Form()
    form.Text = "Choose Levels"
    form.ClientSize = Size(300, 340)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.TopMost = True

    lst = CheckedListBox()
    lst.Location = Point(12, 12)
    lst.Size = Size(276, 270)
    lst.CheckOnClick = True
    for name in level_names:
        lst.Items.Add(name, True)

    btn_ok = _button("OK", 132, DialogResult.OK, y=298)
    btn_cancel = _button("Cancel", 213, DialogResult.Cancel, y=298)

    for c in (lst, btn_ok, btn_cancel):
        form.Controls.Add(c)
    form.AcceptButton = btn_ok
    form.CancelButton = btn_cancel

    if form.ShowDialog() != DialogResult.OK:
        return None

    return [str(lst.Items[i]) for i in range(lst.Items.Count)
            if lst.GetItemChecked(i)]
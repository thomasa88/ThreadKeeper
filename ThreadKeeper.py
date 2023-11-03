#Author-Thomas Axelsson
#DescriptionReinstalls thread definitions every time they are removed.

# This file is part of ThreadKeeper, a Fusion 360 add-in for automatically
# restoring thread definitions after Fusion 360 update.
#
# Copyright (c) 2020 Thomas Axelsson
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import adsk.core, adsk.fusion, adsk.cam, traceback

import os
import pathlib
import platform
import shutil
import subprocess

NAME = 'ThreadKeeper'

# Must import lib as unique name, to avoid collision with other versions
# loaded by other add-ins
from .thomasa88lib import utils
from .thomasa88lib import events
from .thomasa88lib import manifest
from .thomasa88lib import error
from .thomasa88lib import settings

# Force modules to be fresh during development
import importlib
importlib.reload(thomasa88lib.utils)
importlib.reload(thomasa88lib.events)
importlib.reload(thomasa88lib.manifest)
importlib.reload(thomasa88lib.error)
importlib.reload(thomasa88lib.settings)

PANEL_ID = 'thomasa88_ThreadKeeperPanel'
DIRECTORY_CMD_DEF_ID = 'thomasa88_ThreadKeeperDirectory'
FUSION_DIRECTORY_CMD_DEF_ID = 'thomasa88_ThreadKeeperFusionDirectory'
FORCE_SYNC_CMD_DEF_ID = 'thomasa88_ThreadKeeperForceSync'
CHANGE_DIR_CMD_DEF_ID = 'thomasa88_ThreadKeeperChangeDirectory'

app_ = None
ui_ = None
panel_ = None
fusion_thread_dir_ = None
platform_ = platform.system()
default_thread_dir_ = str(pathlib.Path(thomasa88lib.utils.get_file_dir()) / 'Threads')

error_catcher_ = thomasa88lib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager_ = thomasa88lib.events.EventsManager(error_catcher_)
manifest_ = thomasa88lib.manifest.read()

settings_ = thomasa88lib.settings.SettingsManager({
    # Storing None, for the unlikely case that the add-ins directory
    # is changed in a newer Fusion 360 version
    'thread_directory': None
})

def get_thread_dir():
    thread_dir = settings_['thread_directory']
    if thread_dir is None:
        thread_dir = default_thread_dir_
    return pathlib.Path(thread_dir)

def set_thread_dir(path):
    settings_['thread_directory'] = str(path)

def run(context):
    global app_
    global ui_
    global panel_
    global fusion_thread_dir_
    with error_catcher_:
        app_ = adsk.core.Application.get()
        ui_ = app_.userInterface

        local_thread_dir = get_thread_dir()
        create_thread_dir(local_thread_dir)

        # https://knowledge.autodesk.com/support/fusion-360/learn-explore/caas/sfdcarticles/sfdcarticles/Custom-Threads-in-Fusion-360.html
        # Windows location:
        # %localappdata%\Autodesk\webdeploy\Production\<version ID>\Fusion\Server\Fusion\Configuration\ThreadData
        # Mac location:
        # /Users/<user>/Library/Application Support/Autodesk/webdeploy/production/<version ID>/Autodesk Fusion 360.app/Contents/Libraries/Applications/Fusion/Fusion/Server/Fusion/Configuration/ThreadData

        fusion_deploy_folder = pathlib.Path(thomasa88lib.utils.get_fusion_deploy_folder())
        if platform_ == 'Windows':
            fusion_thread_dir_ = (fusion_deploy_folder /
                                 'Fusion' / 'Server' / 'Fusion' / 'Configuration' / 'ThreadData')
        else:
            fusion_thread_dir_ = (fusion_deploy_folder /
                                  'Autodesk Fusion 360.app' / 'Contents' / 'Libraries' / 'Applications' /
                                  'Fusion' / 'Fusion' / 'Server' / 'Fusion' / 'Configuration' / 'ThreadData')
        
        tab = ui_.workspaces.itemById('FusionSolidEnvironment').toolbarTabs.itemById('ToolsTab')
        panel_ = tab.toolbarPanels.itemById(PANEL_ID)
        if panel_:
            panel_.deleteMe()
        panel_ = tab.toolbarPanels.add(PANEL_ID, f'{NAME}')

        directory_cmd_def = ui_.commandDefinitions.itemById(DIRECTORY_CMD_DEF_ID)
        if directory_cmd_def:
            directory_cmd_def.deleteMe()
        directory_cmd_def = ui_.commandDefinitions.addButtonDefinition(DIRECTORY_CMD_DEF_ID,
                                                                       f'Open ThreadKeeper directory',
                                                                       f'Open the {NAME} threads directory.\n\n'
                                                                       'Put threads that you want to keep into this directory.',
                                                                       './resources/thread_folder')
        events_manager_.add_handler(directory_cmd_def.commandCreated,
                                    callback=lambda args: open_folder(get_thread_dir()))
        directory_control = panel_.controls.addCommand(directory_cmd_def)
        directory_control.isPromoted = True
        directory_control.isPromotedByDefault = True

        fusion_directory_cmd_def = ui_.commandDefinitions.itemById(FUSION_DIRECTORY_CMD_DEF_ID)
        if fusion_directory_cmd_def:
            fusion_directory_cmd_def.deleteMe()
        fusion_directory_cmd_def = ui_.commandDefinitions.addButtonDefinition(FUSION_DIRECTORY_CMD_DEF_ID,
                                                                       'Open Fusion 360™ directory',
                                                                       'Open the Fusion 360™ threads directory.\n\n'
                                                                       'This is the directory which Fusion 360™ reads '
                                                                       'threads from. Threads will be synced to this '
                                                                       'directory.\n\n'
                                                                       'Open this directory to inspect what thread definitions '
                                                                       'are installed and to remove thread definitions.',
                                                                       './resources/fusion_thread_folder')
        events_manager_.add_handler(fusion_directory_cmd_def.commandCreated,
                                    callback=lambda args: open_folder(fusion_thread_dir_))
        panel_.controls.addCommand(fusion_directory_cmd_def)

        force_sync_cmd_def = ui_.commandDefinitions.itemById(FORCE_SYNC_CMD_DEF_ID)
        if force_sync_cmd_def:
            force_sync_cmd_def.deleteMe()
        force_sync_cmd_def = ui_.commandDefinitions.addButtonDefinition(FORCE_SYNC_CMD_DEF_ID,
                                                                       'Force sync',
                                                                       f'Copies threads from the {NAME} threads directory'
                                                                       'to the Fusion 360™ threads directory.\n\n'
                                                                       'Files with the same name are overwritten. '
                                                                       'No files are removed.\n\n'
                                                                       'Use this command when you have put new (versions of) '
                                                                       f'thread files in the {NAME} threads directory.',
                                                                       './resources/force_sync')
        events_manager_.add_handler(force_sync_cmd_def.commandCreated,
                                    callback=force_sync_handler)
        panel_.controls.addCommand(force_sync_cmd_def)

        panel_.controls.addSeparator()

        change_dir_cmd_def = ui_.commandDefinitions.itemById(CHANGE_DIR_CMD_DEF_ID)
        if change_dir_cmd_def:
            change_dir_cmd_def.deleteMe()
        change_dir_cmd_def = ui_.commandDefinitions.addButtonDefinition(CHANGE_DIR_CMD_DEF_ID,
                                                                       'Change ThreadKeeper directory...',
                                                                       f'Change which directory {NAME} uses to store '
                                                                       'a backup of your threads.\n\n'
                                                                       f'Current {NAME} directory content will be '
                                                                       'copied to the new directory.',
                                                                       '')
        events_manager_.add_handler(change_dir_cmd_def.commandCreated,
                                    callback=change_dir_handler)
        panel_.controls.addCommand(change_dir_cmd_def)

        # Using startupCompleted does not let the UI load before we run, so it's no point in using that.
        # Just running sync directly. Also, the benefit is that threads are more likely to be ready
        # when Fusion checks for them.
        sync()

def stop(context):
    with error_catcher_:
        events_manager_.clean_up()

        panel_.deleteMe()

def open_folder(path):
    if platform_ == 'Windows':
        os.startfile(path)
    else:
        subprocess.Popen(['open', '--', str(path)])

def sync(force=False, always_msgbox=False):
    global fusion_thread_dir_
    
    local_thread_dir = get_thread_dir()
    files = local_thread_dir.glob('**/*.xml')
    
    restore_count = 0
    for src_file in files:
        dest_file = fusion_thread_dir_ / src_file.name
        if force or not dest_file.exists():
            # shutil is extremely slow. Using shell instead.
            # We must flatten the directory structure.
            if platform_ == 'Windows':
                subprocess.check_call(f'copy "{src_file}" "{dest_file}"', shell=True)
            else:
                subprocess.check_call(f'cp -- "{src_file}" "{dest_file}"', shell=True)
            restore_count += 1
    if always_msgbox or restore_count > 0:
        action = "Restored" if not force else "Synced"
        ui_.messageBox(f"{action} {restore_count} thread files.\n\n"
                       "You might have to restart Fusion 360™ for the thread definitions to load.",
                       f"{NAME} Sync")


def force_sync_handler(args: adsk.core.CommandCreatedEventArgs):
    answer = ui_.messageBox('Any old thread files in the Fusion 360™ directory will be overwritten. Continue?',
                            f'{NAME} Sync Confirmation', adsk.core.MessageBoxButtonTypes.YesNoButtonType)
    if answer == adsk.core.DialogResults.DialogYes:
        sync(force=True, always_msgbox=True)

def change_dir_handler(args: adsk.core.CommandCreatedEventArgs):
    dialog = ui_.createFolderDialog()
    old_dir = get_thread_dir()
    dialog.initialDirectory = str(old_dir)
    dialog.title = f'Choose {NAME} directory'
    folder_answer = dialog.showDialog()
    if folder_answer == adsk.core.DialogResults.DialogOK:
        new_dir = pathlib.Path(dialog.folder)

        if new_dir == old_dir:
            # TODO: Prompt user to select again?
            return

        # Gave up on moving the files as we needed to call a separate remove command on windows
        # and we don't want to accidentally remove the wrong files. Maybe use Python pathlib/os
        # functions in the future...
        if len(os.listdir(old_dir)) != 0:
            move_answer = ui_.messageBox("Do you want to copy your existing thread definitions to the new directory?\n\n"
                                         "Existing files in the new directory will be overwritten.", f"{NAME}",
                                         adsk.core.MessageBoxButtonTypes.YesNoCancelButtonType)
        else:
            move_answer = adsk.core.DialogResults.DialogNo

        if move_answer == adsk.core.DialogResults.DialogCancel:
            return

        create_thread_dir(new_dir)

        set_thread_dir(new_dir)

        if move_answer == adsk.core.DialogResults.DialogYes:
            # In case of move: new_dir might already have existed, so we can't just move
            # the old_dir and rename it

            if old_dir in new_dir.parents or new_dir in old_dir.parents:
                ui_.messageBox('The new directory is a child or parent of the old directory. No copy will be done. '
                               'You have to copy the files manually.', NAME)
                return

            ### TODO: Progress dialog. Looks like we must return to the main loop for it to
            # interact correctly with MessageBox: Completion message shows before progress.hide(),
            # at least on Mac.
            #progress = ui_.createProgressDialog()
            #progress.show(NAME, "Copying thread definitions...", 0, 100, 1)

            if platform_ == 'Windows':
                # "move" does not handle "move a\* b" and it also scream when moving directories
                # on top of each other.
                # "robocopy" copies files and then deletes the source, but we could live with that
                # as Python file operations are so slow. It seems to be a tool similar to rsync.
                # "robocopy" removes the source directory when using /MOVE and in case something is
                # using it, we get a ghost folder that reports Access Denied, that we cannot
                # replace...
                # f'robocopy "{old_dir}" "{new_dir}" /MOVE /E /IS /IT /IM'
                # So going for old trusted xcopy instead.
                subprocess.check_call(f'xcopy /e /i /y "{old_dir}" "{new_dir}\"', shell=True, timeout=30)
            else:
                subprocess.check_call(f'cp -r -- "{old_dir}/"* "{new_dir}/"', shell=True, timeout=30)
            
            #progress.progressValue = 100
            #progress.hide()

        ui_.messageBox(f'Thread directory changed!\n\n'
                       f'Old: {old_dir}\nNew: {new_dir}', f'{NAME}')

def create_thread_dir(dir_path):
    dir_path.mkdir(exist_ok=True)


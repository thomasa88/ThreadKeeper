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
import shutil
import subprocess

NAME = 'ThreadKeeper'

# Must import lib as unique name, to avoid collision with other versions
# loaded by other add-ins
from .thomasa88lib import utils
from .thomasa88lib import events
#from .thomasa88lib import timeline
from .thomasa88lib import manifest
from .thomasa88lib import error

# Force modules to be fresh during development
import importlib
importlib.reload(thomasa88lib.utils)
importlib.reload(thomasa88lib.events)
#importlib.reload(thomasa88lib.timeline)
importlib.reload(thomasa88lib.manifest)
importlib.reload(thomasa88lib.error)

PANEL_ID = 'thomasa88_ThreadKeeperPanel'
MAIN_DROPDOWN_ID = 'thomasa88_ThreadKeeperMainDropdown'
DIRECTORY_CMD_DEF_ID = 'thomasa88_ThreadKeeperDirectory'
FUSION_DIRECTORY_CMD_DEF_ID = 'thomasa88_ThreadKeeperFusionDirectory'
FORCE_SYNC_CMD_DEF_ID = 'thomasa88_ThreadKeeperForceSync'

app_ = None
ui_ = None
panel_ = None
local_thread_dir_ = None
fusion_thread_dir_ = None

error_catcher_ = thomasa88lib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager_ = thomasa88lib.events.EventsManager(error_catcher_)
manifest_ = thomasa88lib.manifest.read()


def run(context):
    global app_
    global ui_
    global panel_
    global local_thread_dir_
    global fusion_thread_dir_
    with error_catcher_:
        app_ = adsk.core.Application.get()
        ui_ = app_.userInterface

        local_thread_dir_ = pathlib.Path(thomasa88lib.utils.get_file_dir()) / 'Threads'
        if not os.path.exists(local_thread_dir_):
            os.mkdir(local_thread_dir_)
        
        # https://knowledge.autodesk.com/support/fusion-360/learn-explore/caas/sfdcarticles/sfdcarticles/Custom-Threads-in-Fusion-360.html
        # %localappdata%\Autodesk\webdeploy\Production\<version ID>\Fusion\Server\Fusion\Configuration\ThreadData
        fusion_thread_dir_ = (pathlib.Path(thomasa88lib.utils.get_fusion_deploy_folder()) / 
                             'Fusion' / 'Server' / 'Fusion' / 'Configuration' / 'ThreadData')
        
        tab = ui_.allToolbarTabs.itemById('ToolsTab')
        panel_ = tab.toolbarPanels.itemById(PANEL_ID)
        if panel_:
            panel_.deleteMe()
        panel_ = tab.toolbarPanels.add(PANEL_ID, f'{NAME}')

        directory_cmd_def = ui_.commandDefinitions.itemById(DIRECTORY_CMD_DEF_ID)
        if directory_cmd_def:
            directory_cmd_def.deleteMe()
        directory_cmd_def = ui_.commandDefinitions.addButtonDefinition(DIRECTORY_CMD_DEF_ID,
                                                                       f'Open threads directory',
                                                                       f'Open the threads directory of {NAME}.\n\n'
                                                                       'Put threads that you want to keep into this directory.',
                                                                       './resources/thread_folder')
        events_manager_.add_handler(directory_cmd_def.commandCreated,
                                    callback=lambda args: os.startfile(local_thread_dir_))
        directory_control = panel_.controls.addCommand(directory_cmd_def)
        directory_control.isPromoted = True
        directory_control.isPromotedByDefault = True

        fusion_directory_cmd_def = ui_.commandDefinitions.itemById(FUSION_DIRECTORY_CMD_DEF_ID)
        if fusion_directory_cmd_def:
            fusion_directory_cmd_def.deleteMe()
        fusion_directory_cmd_def = ui_.commandDefinitions.addButtonDefinition(FUSION_DIRECTORY_CMD_DEF_ID,
                                                                       'Open Fusion 360™ directory',
                                                                       'Open the threads directory of Fusion 360™.\n\n'
                                                                       'This is the directory which Fusion 360™ reads '
                                                                       'threads from. Threads will be synced to this '
                                                                       'directory.',
                                                                       './resources/fusion_thread_folder')
        events_manager_.add_handler(fusion_directory_cmd_def.commandCreated,
                                    callback=lambda args: os.startfile(fusion_thread_dir_))
        panel_.controls.addCommand(fusion_directory_cmd_def)

        force_sync_cmd_def = ui_.commandDefinitions.itemById(FORCE_SYNC_CMD_DEF_ID)
        if force_sync_cmd_def:
            force_sync_cmd_def.deleteMe()
        force_sync_cmd_def = ui_.commandDefinitions.addButtonDefinition(FORCE_SYNC_CMD_DEF_ID,
                                                                       'Force sync',
                                                                       f'Copies threads from the threads directory of {NAME} '
                                                                       'to the threads directory of Fusion 360™. Files with '
                                                                       'the same name are overwritten.\n\n'
                                                                       'Use this command when you have put new versions of'
                                                                       f'your thread files in {NAME} thread directory.',
                                                                       './resources/force_sync')
        events_manager_.add_handler(force_sync_cmd_def.commandCreated,
                                    callback=force_sync_handler)
        panel_.controls.addCommand(force_sync_cmd_def)

        sync()

def stop(context):
    with error_catcher_:
        events_manager_.clean_up()

        panel_.deleteMe()

def sync(force=False, always_msgbox=False):
    global local_thread_dir_
    global fusion_thread_dir_
    
    files = local_thread_dir_.glob('**/*.xml')
    
    restore_count = 0
    for src_file in files:
        dest_file = fusion_thread_dir_ / src_file.name
        if force or not dest_file.exists():
            # shutil is extremely slow. Using shell instead.
            #shutil.copyfile(src_file, dest_file)
            subprocess.call(f'copy "{src_file}" "{dest_file}"', shell=True)
            restore_count += 1
    if always_msgbox or restore_count > 0:
        action = "Restored" if not force else "Synced"
        ui_.messageBox(f"{action} {restore_count} thread files.\n\n"
                       "Please restart Fusion 360™ to reload the thread definitions.",
                       f"{NAME} Sync")


def force_sync_handler(args: adsk.core.CommandCreatedEventArgs):
    answer = ui_.messageBox('Any old thread files in the Fusion 360™ directory will be overwritten. Continue?',
                            f'{NAME} Sync Confirmation', adsk.core.MessageBoxButtonTypes.YesNoButtonType)
    if answer == adsk.core.DialogResults.DialogYes:
        sync(force=True, always_msgbox=True)
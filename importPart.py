'''
Used for importing parts from other FreeCAD documents.
When update parts is executed, this library import or updates the parts in the assembly document.
'''
from assembly2lib import *
from assembly2lib import __dir__
from PySide import QtGui
import os, numpy
import lib3D

def importPart( filename, partName=None ):
    updateExistingPart = partName <> None
    if updateExistingPart:
        FreeCAD.Console.PrintMessage("updating part %s from %s\n" % (partName,filename))
    else:
        FreeCAD.Console.PrintMessage("importing part from %s\n" % filename)
        
    doc_already_open = filename in [ d.FileName for d in FreeCAD.listDocuments().values() ] 
    debugPrint(4, "%s open already %s" % (filename, doc_already_open))
    if not doc_already_open:
        currentDoc = FreeCAD.ActiveDocument.Name
        FreeCAD.open(filename)
        FreeCAD.setActiveDocument(currentDoc)
    doc = [ d for d in FreeCAD.listDocuments().values()
            if d.FileName == filename][0]
    debugPrint(3, '%s objects %s' % (doc.Name, doc.Objects))
    visibleObjects = [ obj for obj in doc.Objects
                       if hasattr(obj,'ViewObject') and obj.ViewObject.isVisible()
                       and hasattr(obj,'Shape') and len(obj.Shape.Faces) > 0] # len(obj.Shape.Faces) > 0 to avoid sketches
    if len(visibleObjects) <> 1:
        if not updateExistingPart:
            msg = "A part can only be imported from a FreeCAD document with exactly one visible part. Aborting operation"
            QtGui.QMessageBox.information(  QtGui.qApp.activeWindow(), "Value Error", msg )
        else:
            msg = "Error updating part from %s: A part can only be imported from a FreeCAD document with exactly one visible part. Aborting update of %s" % (partName, filename)
            QtGui.QMessageBox.information(  QtGui.qApp.activeWindow(), "Value Error", msg )
        #QtGui.QMessageBox.warning( QtGui.qApp.activeWindow(), "Value Error!", msg, QtGui.QMessageBox.StandardButton.Ok )
        return
    obj_to_copy = visibleObjects[0]
    if updateExistingPart:
        obj = FreeCAD.ActiveDocument.getObject(partName)
        prevPlacement = obj.Placement
    else:
        partName = findUnusedObjectName( doc.Name + '_import' )
        obj = FreeCAD.ActiveDocument.addObject("Part::FeaturePython",partName)
        obj.addProperty("App::PropertyFile",    "sourceFile",    "importPart").sourceFile = filename
        obj.addProperty("App::PropertyFloat", "timeLastImport","importPart")
        obj.setEditorMode("timeLastImport",1)  
        obj.addProperty("App::PropertyBool","fixedPosition","importPart")
        obj.fixedPosition = not any([i.fixedPosition for i in FreeCAD.ActiveDocument.Objects if hasattr(i, 'fixedPosition') ])
    obj.Shape = obj_to_copy.Shape.copy()
    # would this work?:   obj.ViewObject = visibleObjects[0].ViewObject  
    if updateExistingPart:
        obj.Placement = prevPlacement
        obj.touch()
    else:
        #obj.ViewObject.Proxy = ViewProviderProxy_importPart()
        obj.ViewObject.Proxy = 0
        for p in obj_to_copy.ViewObject.PropertiesList: #assuming that the user may change the appearance of parts differently depending on the assembly.
            if hasattr(obj.ViewObject, p):
                setattr(obj.ViewObject, p, getattr(obj_to_copy.ViewObject, p))
    obj.Proxy = Proxy_importPart()
    obj.timeLastImport = os.path.getmtime( obj.sourceFile )
    if not doc_already_open: #then close again
        FreeCAD.closeDocument(doc.Name)
        FreeCAD.setActiveDocument(currentDoc)
    return obj

class Proxy_importPart:
    def execute(self, shape):
        pass

class ImportPartCommand:
    def Activated(self):
        view = FreeCADGui.activeDocument().activeView()
        filename, filetype = QtGui.QFileDialog.getOpenFileName( 
            QtGui.qApp.activeWindow(),
            "Select FreeCAD document to import part from",
            os.path.dirname(FreeCAD.ActiveDocument.FileName),
            "FreeCAD Document (*.fcstd)"
            )
        if filename == '':
            return
        importedObject = importPart( filename )
        FreeCAD.ActiveDocument.recompute()
        if not importedObject.fixedPosition: #will be true for the first imported part 
            PartMover( view, importedObject )
        else:
            from PySide import QtCore
            self.timer = QtCore.QTimer()
            QtCore.QObject.connect(self.timer, QtCore.SIGNAL("timeout()"), self.GuiViewFit)
            self.timer.start( 500 ) #0.5 seconds

    def GuiViewFit(self):
        FreeCADGui.SendMsgToActiveView("ViewFit") #dont know why this does not work
        self.timer.stop()
       
    def GetResources(self): 
        return {
            'Pixmap' : os.path.join( __dir__ , 'importPart.svg' ) , 
            'MenuText': 'Import a part from another FreeCAD document', 
            'ToolTip': 'Import a part from another FreeCAD document'
            } 
FreeCADGui.addCommand('importPart', ImportPartCommand())

class UpdateImportedPartsCommand:
    def Activated(self):
        for obj in FreeCAD.ActiveDocument.Objects:
            if hasattr(obj, 'sourceFile'):
                if not hasattr( obj, 'timeLastImport'):
                    obj.addProperty("App::PropertyFloat", "timeLastImport","importPart") #should default to zero which will force update.
                    obj.setEditorMode("timeLastImport",1)  
                if not os.path.exists( obj.sourceFile ):
                    QtGui.QMessageBox.critical(  QtGui.qApp.activeWindow(), "Source file not found", "update of %s aborted due source file being missing..." % obj.Name )
                    obj.timeLastImport = 0 #force update if users repairs link
                elif os.path.getmtime( obj.sourceFile ) > obj.timeLastImport:
                    importPart( obj.sourceFile, obj.Name )
        FreeCAD.ActiveDocument.recompute()
    def GetResources(self): 
        return {
            'Pixmap' : os.path.join( __dir__ , 'importPart_update.svg' ) , 
            'MenuText': 'Update parts imported into the assembly', 
            'ToolTip': 'Update parts imported into the assembly'
            } 
FreeCADGui.addCommand('updateImportedPartsCommand', UpdateImportedPartsCommand())


class PartMover:
    def __init__(self, view, obj):
        self.obj = obj
        self.initialPostion = self.obj.Placement.Base 
        self.copiedObject = False
        self.view = view
        self.callbackMove = self.view.addEventCallback("SoLocation2Event",self.moveMouse)
        self.callbackClick = self.view.addEventCallback("SoMouseButtonEvent",self.clickMouse)
        self.callbackKey = self.view.addEventCallback("SoKeyboardEvent",self.KeyboardEvent)
    def moveMouse(self, info):
        newPos = self.view.getPoint( *info['Position'] )
        debugPrint(5, 'new position %s' % str(newPos))
        self.obj.Placement.Base = newPos
    def removeCallbacks(self):
        self.view.removeEventCallback("SoLocation2Event",self.callbackMove)
        self.view.removeEventCallback("SoMouseButtonEvent",self.callbackClick)
        self.view.removeEventCallback("SoKeyboardEvent",self.callbackKey)
    def clickMouse(self, info):
        debugPrint(4, 'clickMouse info %s' % str(info))
        if info['Button'] == 'BUTTON1' and info['State'] == 'DOWN':
            if not info['ShiftDown'] and not info['CtrlDown']:
                self.removeCallbacks()
            elif info['ShiftDown']: #copy object
                partName = findUnusedObjectName( self.obj.Name[:self.obj.Name.find('_import') + len('_import')] )
                newObj = FreeCAD.ActiveDocument.addObject("Part::FeaturePython",partName)
                newObj.addProperty("App::PropertyFile",    "sourceFile",    "importPart").sourceFile = self.obj.sourceFile
                newObj.addProperty("App::PropertyFloat", "timeLastImport","importPart").timeLastImport =  self.obj.timeLastImport
                newObj.setEditorMode("timeLastImport",1)  
                newObj.addProperty("App::PropertyBool","fixedPosition","importPart").fixedPosition = self.obj.fixedPosition
                newObj.Shape = self.obj.Shape.copy()
                newObj.ViewObject.Proxy = 0
                for p in self.obj.ViewObject.PropertiesList: #assuming that the user may change the appearance of parts differently depending on the assembly.
                    if hasattr(newObj.ViewObject, p):
                        setattr(newObj.ViewObject, p, getattr(self.obj.ViewObject, p))
                newObj.Proxy = Proxy_importPart()
                newObj.Placement.Base = self.obj.Placement.Base
                newObj.Placement.Rotation = self.obj.Placement.Rotation
                self.obj = newObj
                self.copiedObject = True
            elif info['CtrlDown']:
                azi   =  ( numpy.random.rand() - 0.5 )*numpy.pi*2
                ela   =  ( numpy.random.rand() - 0.5 )*numpy.pi
                theta =  ( numpy.random.rand() - 0.5 )*numpy.pi
                axis = lib3D.azimuth_and_elevation_angles_to_axis( azi, ela )
                self.obj.Placement.Rotation.Q = lib3D.quaternion( theta, *axis )
            
    def KeyboardEvent(self, info):
        debugPrint(4, 'KeyboardEvent info %s' % str(info))
        if info['State'] == 'UP' and info['Key'] == 'ESCAPE':
            if not self.copiedObject:
                self.obj.Placement.Base = self.initialPostion
            else:
                FreeCAD.ActiveDocument.removeObject(self.obj.Name)
            self.removeCallbacks()

    

class PartMoverSelectionObserver:
     def __init__(self):
          FreeCADGui.Selection.addObserver(self)  
          FreeCADGui.Selection.removeSelectionGate()
     def addSelection( self, docName, objName, sub, pnt ):
         debugPrint(4,'addSelection: docName,objName,sub = %s,%s,%s' % (docName, objName, sub))
         FreeCADGui.Selection.removeObserver(self) 
         obj = FreeCAD.ActiveDocument.getObject(objName)
         view = FreeCADGui.activeDocument().activeView()
         PartMover( view, obj )


class MovePartCommand:
    def Activated(self):
        selection = FreeCADGui.Selection.getSelectionEx()
        if len(selection) == 1:
            PartMover(  FreeCADGui.activeDocument().activeView(), selection[0].Object )
        else:
            PartMoverSelectionObserver()
       
    def GetResources(self): 
        return {
            'Pixmap' : os.path.join( __dir__ , 'Draft_Move.svg' ) , 
            'MenuText': 'move a part (hold shift to copy)', 
            'ToolTip': 'move a part (hold shift to copy)'
            } 

FreeCADGui.addCommand('assembly2_movepart', MovePartCommand())


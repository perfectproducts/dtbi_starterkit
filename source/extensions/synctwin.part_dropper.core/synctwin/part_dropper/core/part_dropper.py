from http.client import NETWORK_AUTHENTICATION_REQUIRED
from pxr import Usd, UsdGeom, Gf, UsdLux, UsdGeom, Sdf, Tf, UsdPhysics, PhysxSchema
from omni.physx.scripts.physicsUtils import add_ground_plane
from omni.physx.scripts.utils import set_physics_scene_asyncsimrender
from enum import Enum

class PartDropper:

    def __init__(self) -> None:
        self._cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default', 'render'])
        self.reset()

    def set_stage(self, stage: Usd.Stage):
        self.stage = stage

    def has_container(self) -> bool:
        return self.container_path != ""

    def has_part(self) -> bool:
        return self.part_path != ""

    def bounds(self, usd_path) -> Gf.Range3d:
        stage = Usd.Stage.Open(usd_path)
        bounds = self._cache.ComputeWorldBound(stage.GetPrimAtPath("/"))
        stage = None
        return bounds.GetRange()

    def set_container_usd(self, usd_path):
        self.container_path = usd_path
        self.container_bounds = self.bounds(usd_path)
        self.container_size = self.container_bounds.GetSize()
        self.clear_parts()
        if self.has_container():
            self.create_container()

    def clear_parts(self):
        self.part_count = 0
        self._curr_part_prim = None
        if self.stage:
            self.stage.RemovePrim(self._parts_prim_path)

    def set_part_usd(self, usd_path):
        self.part_path = usd_path
        self.part_bounds= self.bounds(usd_path)
        self.part_size = self.part_bounds.GetSize()
        self.clear_parts()
        if self.has_part():
            self.add_part()

    def set_target_count(self, newcount:int):
        self.target_part_count = newcount

    def create_ground_plane(self):
        stage = self.stage
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        # light
        defaultPrimPath = "/World"
        light_path = defaultPrimPath + "/SphereLight"
        stage.RemovePrim(light_path)
        sphereLight = UsdLux.SphereLight.Define(stage, light_path)
        sphereLight.CreateRadiusAttr(150)
        sphereLight.CreateIntensityAttr(30000)
        sphereLight.AddTranslateOp().Set(Gf.Vec3f(650.0, 0.0, 1150.0))

        # Physics scene
        scene = UsdPhysics.Scene.Define(stage, defaultPrimPath + "/physicsScene")
        scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(0.0, 0.0, -1.0))
        scene.CreateGravityMagnitudeAttr().Set(981.0)
        set_physics_scene_asyncsimrender(scene.GetPrim())

        # custom GPU buffers
        physxSceneAPI = PhysxSchema.PhysxSceneAPI.Apply(stage.GetPrimAtPath(defaultPrimPath + "/physicsScene"))
        physxSceneAPI.CreateGpuTempBufferCapacityAttr(16 * 1024 * 1024 * 2)
        physxSceneAPI.CreateGpuHeapCapacityAttr(64 * 1024 * 1024 * 2)
        physxSceneAPI.CreateGpuFoundLostPairsCapacityAttr(256 * 1024 * 2)
        physxSceneAPI.CreateGpuMaxRigidPatchCountAttr(1000000)

        stage.RemovePrim(self._groundplane_prim_path)
        add_ground_plane(stage, self._groundplane_prim_path, "Z", 750.0, Gf.Vec3f(0.0, 0.0, 0), Gf.Vec3f(0.5))

    def create_container(self):
        stage = self.stage
        bbox = self.bounds(self.container_path)
        pcenter = bbox.GetMidpoint()
        pmin = bbox.GetMin()
        psize = bbox.GetSize()

        stage.RemovePrim(self._container_prim_path)
        box_prim = stage.DefinePrim(self._container_prim_path)
        box_prim.GetReferences().AddReference(self.container_path)
        self._container_offset = Gf.Vec3f(-pcenter[0], -pcenter[1], -pmin[2])

        xf = UsdGeom.Xformable(box_prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(self._container_offset)

        UsdPhysics.CollisionAPI.Apply(box_prim)

        meshCollisionAPI = UsdPhysics.MeshCollisionAPI.Apply(box_prim)
        meshCollisionAPI.CreateApproximationAttr().Set("meshSimplification")

        self.container_bounds = self._cache.ComputeWorldBound(box_prim).GetRange()

    def add_part(self):
        stage = self.stage
        self.part_count += 1
        part_path = f"{self._parts_prim_path}/Part_{self.part_count}"
        part_prim = stage.DefinePrim(part_path, "Xform")
        part_prim.GetReferences().AddReference(self.part_path)



        UsdPhysics.CollisionAPI.Apply(part_prim)
        UsdPhysics.RigidBodyAPI.Apply(part_prim)
        meshCollisionAPI = UsdPhysics.MeshCollisionAPI.Apply(part_prim)
        meshCollisionAPI.CreateApproximationAttr().Set("convexHull")


        c = self.part_bounds.GetMidpoint()
        xf = UsdGeom.Xformable(part_prim)
        xf.ClearXformOpOrder()
        xf.AddScaleOp().Set(Gf.Vec3f(self.part_scale_factor, self.part_scale_factor,self.part_scale_factor))
        xf.AddTranslateOp().Set(Gf.Vec3f(-c[0], -c[1], (self.container_size[2]*2)/self.part_scale_factor))
        self._past_part_pos = Gf.Vec3d()
        self._curr_part_prim = part_prim

    def set_part_scale_factor(self, value):
        self.part_scale_factor = value
        self.clear_parts()
        if self.has_part() and self.has_container():
            self.add_part()

    def reset(self):
        self.container_path = ""
        self.part_path = ""
        self.part_size = Gf.Vec3f()
        self.part_scale_factor = 1
        self.container_path = ""
        self.container_size = Gf.Vec3f()
        self._container_offset= Gf.Vec3f()
        self.part_count = 0

        self.target_part_count = 100
        self.stage = None
        self.is_dropping = False
        self.drop_interval_ms = 250
        self._last_drop_time_ms = 0
        self._curr_part_prim = None
        self._past_part_pos = Gf.Vec3d()
        self._root_prim_path = "/World/PartDropper"
        self._container_prim_path = f"{self._root_prim_path}/Container"
        self._parts_prim_path = f"{self._root_prim_path}/Parts"
        self._groundplane_prim_path= f"{self._root_prim_path}/GroundPlane"

    class UpdateResult(Enum):
        IDLE = 0,
        DROPPING = 1,
        PART_DROPPED = 2,
        TARGET_PARTS_REACHED = 3,
        PART_MISSED = 4


    def update(self, now_ms) -> UpdateResult:
        if not self.is_dropping:
            return PartDropper.UpdateResult.IDLE
        if not self._curr_part_prim:
            return PartDropper.UpdateResult.IDLE
            #print(self._curr_part_body)
            #print(self._curr_part_body.GetVelocityAttr().Get())

        elapsed_ms = now_ms - self._last_drop_time_ms
        if elapsed_ms > self.drop_interval_ms:
            self._last_drop_time_ms = now_ms
            local_transformation = UsdGeom.Xformable(self._curr_part_prim).GetLocalTransformation()
            translation: Gf.Vec3d = local_transformation.ExtractTranslation()
            offset = translation-self._past_part_pos
            self._past_part_pos = translation

            if self.part_count >= self.target_part_count:
                self.stop_dropping()
                return PartDropper.UpdateResult.TARGET_PARTS_REACHED
            else:
                self.add_part()
                return PartDropper.UpdateResult.PART_DROPPED
        return PartDropper.UpdateResult.DROPPING


    def start_dropping(self):
        self.clear_parts()

        self.add_part()
        self.is_dropping = True


    def stop_dropping(self):
        self.is_dropping = False


    def export_filled_container(self, path:str) -> bool:
        if path == "":
            return False
        if not path.endswith(".usd"):
            path += ".usd"
        if not self.stage:
            return False
        source_stage = self.stage
        defaultPrimPath = "/World"
        layer = Sdf.Layer.FindOrOpen(path)
        if not layer:
            layer = Sdf.Layer.CreateNew(path)
        else:
            layer.Clear()

        if layer:
            stage = Usd.Stage.Open(layer)
        else:
            return False

        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        box_prim = stage.DefinePrim(f"/World/Box", "Xform")

        container_prim = stage.DefinePrim("/World/Box/Container", "Xform")
        container_prim.GetReferences().AddReference(self.container_path)
        xf= UsdGeom.Xformable(container_prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(self._container_offset)
        num_parts = 0
        for child_prim in source_stage.GetPrimAtPath(self._parts_prim_path).GetChildren():
            num_parts+=1
            part_prim = stage.DefinePrim(f"/World/Box/Parts/Part_{num_parts}", "Xform")
            part_prim.GetReferences().AddReference(self.part_path)

            mat4 = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(child_prim)
            xf = UsdGeom.Xformable(part_prim)
            xf.ClearXformOpOrder()
            xf.AddTransformOp().Set(mat4)

        stage.SetDefaultPrim(stage.GetPrimAtPath(defaultPrimPath))
        stage.GetRootLayer().Save()
        return True
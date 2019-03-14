from nose.tools import (assert_equal, assert_not_equal, assert_almost_equal,
                        raises, assert_true)
from nose.plugins.skip import Skip, SkipTest
import numpy.testing as npt

from test_helpers import data_filename, assert_items_equal

import openpathsampling as paths
import mdtraj as md

from openpathsampling.engines.gromacs import *

import logging
import numpy as np

import shutil


logging.getLogger('openpathsampling.initialization').setLevel(logging.CRITICAL)
logging.getLogger('openpathsampling.ensemble').setLevel(logging.CRITICAL)
logging.getLogger('openpathsampling.storage').setLevel(logging.CRITICAL)
logging.getLogger('openpathsampling.netcdfplus').setLevel(logging.CRITICAL)

# check whether we have Gromacs 5 available; otherwise some tests skipped
# lazily use subprocess here; in case we ever change use of psutil
import subprocess
import os
devnull = open(os.devnull, 'w')
try:
    has_gmx = not subprocess.call(["gmx", "-version"], stdout=devnull,
                                  stderr=devnull)
except OSError:
    has_gmx = False
finally:
    devnull.close()


class TestGromacsEngine(object):
    # Files used (in test_data/gromacs_engine/)
    # conf.gro, md.mdp, topol.top : standard Gromacs input files
    # project_trr/0000000.trr : working file, 4 frames
    # project_trr/0000099.trr : 49 working frames, final frame partial
    def setup(self):
        self.test_dir = data_filename("gromacs_engine")
        self.engine = Engine(gro="conf.gro",
                             mdp="md.mdp",
                             top="topol.top",
                             options={},
                             base_dir=self.test_dir,
                             prefix="project")

    def teardown(self):
        files = ['topol.tpr', 'mdout.mdp', 'initial_frame.trr',
                 self.engine.trajectory_filename(1)]
        for f in files:
            if os.path.isfile(f):
                os.remove(f)
            if os.path.isfile(os.path.join(self.engine.base_dir, f)):
                os.remove(os.path.join(self.engine.base_dir, f))
        shutil.rmtree(self.engine.prefix + "_log")
        shutil.rmtree(self.engine.prefix + "_edr")

    def test_read_frame_from_file_success(self):
        # when the frame is present, we should return it
        fname = os.path.join(self.test_dir, "project_trr", "0000000.trr")
        result = self.engine.read_frame_from_file(fname, 0)
        assert_true(isinstance(result, ExternalMDSnapshot))
        assert_equal(result.file_name, fname)
        assert_equal(result.file_position, 0)
        # TODO: add caching of xyz, vel, box; check that we have it now

        fname = os.path.join(self.test_dir, "project_trr", "0000000.trr")
        result = self.engine.read_frame_from_file(fname, 3)
        assert_true(isinstance(result, ExternalMDSnapshot))
        assert_equal(result.file_name, fname)
        assert_equal(result.file_position, 3)

    def test_read_frame_from_file_partial(self):
        # if a frame is partial, return 'partial'
        fname = os.path.join(self.test_dir, "project_trr", "0000099.trr")
        frame_2 = self.engine.read_frame_from_file(fname, 49)
        assert_true(isinstance(frame_2, ExternalMDSnapshot))
        frame_3 = self.engine.read_frame_from_file(fname, 50)
        assert_equal(frame_3, "partial")

    def test_read_frame_from_file_none(self):
        # if a frame is beyond the last frame, return None
        fname = os.path.join(self.test_dir, "project_trr", "0000000.trr")
        result = self.engine.read_frame_from_file(fname, 4)
        assert_equal(result, None)

    def test_write_frame_to_file_read_back(self):
        # write random frame; read back
        # sinfully, we start by reading in a frame to get the correct dims
        fname = os.path.join(self.test_dir, "project_trr", "0000000.trr")
        tmp = self.engine.read_frame_from_file(fname, 0)
        shape = tmp.xyz.shape
        xyz = np.random.randn(*shape)
        vel = np.random.randn(*shape)
        box = np.random.randn(3, 3)
        traj_50 = self.engine.trajectory_filename(50)
        # clear it out, in case it exists from a previous failed test
        if os.path.isfile(traj_50):
            os.remove(traj_50)
        file_49 = os.path.join(self.test_dir, "project_trr", "0000049.trr")
        snap = ExternalMDSnapshot(file_name=file_49, file_position=2,
                                  engine=self.engine)
        snap.set_details(xyz, vel, box)
        self.engine.write_frame_to_file(traj_50, snap)

        snap2 = self.engine.read_frame_from_file(traj_50, 0)
        assert_equal(snap2.file_name, traj_50)
        assert_equal(snap2.file_position, 0)
        npt.assert_array_almost_equal(snap.xyz, snap2.xyz)
        npt.assert_array_almost_equal(snap.velocities, snap2.velocities)
        npt.assert_array_almost_equal(snap.box_vectors, snap2.box_vectors)

        if os.path.isfile(traj_50):
            os.remove(traj_50)

    def test_set_filenames(self):
        test_engine = Engine(gro="conf.gro", mdp="md.mdp", top="topol.top",
                             base_dir=self.test_dir, options={},
                             prefix="proj")
        test_engine.set_filenames(0)
        assert test_engine.input_file == \
                os.path.join(self.test_dir, "initial_frame.trr")
        assert test_engine.output_file == \
                os.path.join(self.test_dir, "proj_trr", "0000001.trr")
        assert_equal(test_engine.edr_file,
                     os.path.join(self.test_dir, "proj_edr", "0000001.edr"))
        assert_equal(test_engine.log_file,
                     os.path.join(self.test_dir, "proj_log", "0000001.log"))

        test_engine.set_filenames(99)
        assert_equal(test_engine.input_file,
                     os.path.join(self.test_dir, "initial_frame.trr"))
        assert_equal(test_engine.output_file,
                     os.path.join(self.test_dir, "proj_trr", "0000100.trr"))
        assert_equal(test_engine.edr_file,
                     os.path.join(self.test_dir, "proj_edr", "0000100.edr"))
        assert_equal(test_engine.log_file,
                     os.path.join(self.test_dir, "proj_log", "0000100.log"))

    def test_engine_command(self):
        test_engine = Engine(gro="conf.gro", mdp="md.mdp", top="topol.top",
                             base_dir=self.test_dir, options={},
                             prefix="proj")
        test_engine.set_filenames(0)
        tpr = os.path.join("topol.tpr")
        trr = os.path.join(self.test_dir, "proj_trr", "0000001.trr")
        edr = os.path.join(self.test_dir, "proj_edr", "0000001.edr")
        log = os.path.join(self.test_dir, "proj_log", "0000001.log")
        beauty = test_engine.engine_command()
        truth = "gmx mdrun -s {tpr} -o {trr} -e {edr} -g {log} ".format(
                    tpr=tpr, trr=trr, edr=edr, log=log
        )  # space at the end before args (args is empty)
        assert len(beauty) == len(truth)
        assert beauty == truth

    def test_generate(self):
        if not has_gmx:
            raise SkipTest("Gromacs 5 (gmx) not found. Skipping test.")

        traj_0 = self.engine.trajectory_filename(0)
        snap = self.engine.read_frame_from_file(traj_0, 0)
        self.engine.set_filenames(0)

        ens = paths.LengthEnsemble(3)
        traj = self.engine.generate(snap, running=[ens.can_append])
        assert_equal(self.engine.proc.is_running(), False)
        assert_equal(len(traj), 3)
        ttraj = md.load(self.engine.trajectory_filename(1),
                        top=self.engine.gro)
        # the mdp suggests a max length of 100 frames
        assert_true(len(ttraj) < 100)

    def test_prepare(self):
        if not has_gmx:
            raise SkipTest("Gromacs 5 (gmx) not found. Skipping test.")
        self.engine.set_filenames(0)
        traj_0 = self.engine.trajectory_filename(0)
        snap = self.engine.read_frame_from_file(traj_0, 0)
        self.engine.write_frame_to_file(self.engine.input_file, snap)
        files = ['topol.tpr', 'mdout.mdp']
        for f in files:
            if os.path.isfile(f):
                raise AssertionError("File " + str(f) + " already exists!")

        assert_equal(self.engine.prepare(), 0)
        for f in files:
            if not os.path.isfile(f):
                raise AssertionError("File " + str(f) + " was not created!")

        for f in files:
            os.remove(f)

    def test_open_file_caching(self):
        # read several frames from one file, then switch to another file
        # first read from 0000000, then 0000099
        pass

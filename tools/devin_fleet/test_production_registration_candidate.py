import unittest
import uuid
from unittest.mock import patch
import production_registration_candidate as candidate


class CandidateTests(unittest.TestCase):
    def current(self):
        return {'schema':1,'distro':'EBase-Sandboxes','user':'fleet',
            'resources_per_sandbox':{'cpus':2,'memory':'4g'},'production_enabled':False,
            'simultaneous_capacity_verified':1,
            'roles':{role:{'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,role)),'name':'e-base-'+role}
                     for role in candidate.ROLES}}

    def test_composes_without_mutating_current(self):
        current=self.current();before=repr(current)
        value=candidate.compose(current,root_identity='a'*32,migration_epoch=str(uuid.uuid4()))
        self.assertEqual(repr(current),before)
        self.assertTrue(value['production_enabled'])
        self.assertEqual(value['validation_image_id'],candidate.VALIDATION_IMAGE)
        self.assertTrue(all(e['image_digest']==candidate.ROLE_IMAGE for e in value['roles'].values()))
        self.assertIs(candidate.validate(value),value)

    def test_invalid_source_rejected(self):
        for change in ({'production_enabled':True},{'simultaneous_capacity_verified':2},
                       {'roles':{}},{'schema':True}):
            with self.assertRaises(ValueError):
                candidate.compose(dict(self.current(),**change),root_identity='a'*32,
                                  migration_epoch=str(uuid.uuid4()))

    def test_invalid_identity_rejected(self):
        for root,epoch in (('../x',str(uuid.uuid4())),('a'*32,'bad'),('A'*32,str(uuid.uuid4()))):
            with self.assertRaises((ValueError,AttributeError)):
                candidate.compose(self.current(),root_identity=root,migration_epoch=epoch)

    def test_duplicate_role_ids_rejected(self):
        value=candidate.compose(self.current(),root_identity='a'*32,migration_epoch=str(uuid.uuid4()))
        value['roles']['machine']['id']=value['roles']['coordinator']['id']
        with self.assertRaises(ValueError):candidate.validate(value)


if __name__=='__main__':unittest.main()

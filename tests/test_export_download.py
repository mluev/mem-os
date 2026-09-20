import tempfile
from pathlib import Path

from memkit import api, config, jobs
from tests.httpharness import ApiTestCase


class ExportDownloadTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config.get_settings().export_dir = self.directory

    def make_export(self, *, user_id=None, kind="export", path=None, complete=True):
        artifact = path or self.directory / "export.json"
        artifact.write_text('{"memories":[]}')
        identifier = jobs.create(self.db, kind=kind, user_id=user_id or self.team.alice_id)
        if complete:
            jobs.finish(self.db, identifier, status="complete", result={"path": str(artifact)})
        return identifier

    def test_owner_downloads_completed_export(self):
        identifier = self.make_export()
        response = self.client.get(f"/v1/jobs/{identifier}/download", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"memories": []})
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_real_export_worker_produces_downloadable_artifact(self):
        response = self.client.post("/v1/export", headers=self.auth)
        identifier = response.json()["job_id"]
        api._run_export(identifier)
        job = jobs.get(self.db, identifier)
        self.assertEqual(job["status"], "complete", job.get("error"))
        downloaded = self.client.get(f"/v1/jobs/{identifier}/download", headers=self.auth)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.json()["format"], "memkit-user-export-v2")

    def test_other_user_and_admin_cannot_download_someone_elses_export(self):
        identifier = self.make_export()
        self.assertEqual(
            self.client.get(f"/v1/jobs/{identifier}/download", headers=self.as_bob).status_code, 404
        )
        other = self.make_export(user_id=self.team.bob_id)
        self.assertEqual(
            self.client.get(f"/v1/jobs/{other}/download", headers=self.auth).status_code, 404
        )

    def test_unfinished_nonexport_and_unknown_jobs(self):
        pending = self.make_export(complete=False)
        self.assertEqual(
            self.client.get(f"/v1/jobs/{pending}/download", headers=self.auth).status_code, 409
        )
        nonexport = self.make_export(kind="reindex")
        self.assertEqual(
            self.client.get(f"/v1/jobs/{nonexport}/download", headers=self.auth).status_code, 404
        )
        self.assertEqual(
            self.client.get("/v1/jobs/not-a-uuid/download", headers=self.auth).status_code, 404
        )

    def test_path_escape_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "private.json"
            identifier = self.make_export(path=outside)
            self.assertEqual(
                self.client.get(f"/v1/jobs/{identifier}/download", headers=self.auth).status_code,
                404,
            )
            link = self.directory / "link.json"
            link.symlink_to(outside)
            identifier = self.make_export(path=link)
            self.assertEqual(
                self.client.get(f"/v1/jobs/{identifier}/download", headers=self.auth).status_code,
                404,
            )

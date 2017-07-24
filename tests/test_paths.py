import os,  paths

if os.name == "nt":
	def test_drive_path():
	    assert paths.root_as_str_from_abspath('Z:\\thisis\\a\\path') == 'z:\\'

	def test_drive_path_alt():
	    assert paths.root_as_str_from_abspath('Z:/some/6546/path/thing.scala') == 'z:\\'

	def test_network_path():
	    assert paths.root_as_str_from_abspath('//STORAGE/misc/server/a/b/c') == '\\\\storage\\misc'
else:
	def test_drive_path():
	    assert paths.root_as_str_from_abspath('/this/is/a/path') == '/'

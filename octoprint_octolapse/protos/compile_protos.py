# Working directory should be octoprint_octolapse.

import os
import subprocess


def generate_py():
    import_path = os.path.abspath("protos")
    python_out_dir = os.path.abspath("bin/python")

    proto_files = [os.path.abspath(os.path.join('protos', f)) for f in os.listdir('protos') if os.path.splitext(f)[1] == '.proto']

    # Make the directory.
    if not os.path.exists(python_out_dir):
        os.makedirs(python_out_dir)
    # Make __init__.py files in every level of the directory.
    # TODO(Shadowen): do this.

    command = "protoc -I={} --python_out={} {}".format(import_path, python_out_dir, ' '.join(proto_files))
    print(command)
    subprocess.check_call(command.split(' '))

def generate_js():
    pass # TODO(Shadowen): Implement this.


if __name__ == '__main__':
    generate_py()
    generate_js()

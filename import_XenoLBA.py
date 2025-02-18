import sys
import os
import struct
import re
import csv

re_name = re.compile(r"(.*);([0-9]+)")
block_size = 2352

def read_sector_form1(f, lba, count):
    f.seek(lba * block_size)
    data = b""
    for _ in range(count):
        block = f.read(block_size)
        data += block[24:2048+24]
    return data

def read_dir(f, path, dir_pos, dir_size, parent):
    dir_data = read_sector_form1(f, dir_pos, (dir_size + 2047) // 2048)
    file_list = []
    pos = 0

    while pos < len(dir_data):
        (entry_size, file_pos, file_len, attr, name_len) = struct.unpack_from("<BxIxxxxIxxxxxxxxxxxBxxxxxxB", dir_data, pos)

        if entry_size > 0:
            hidden = (attr & 1) != 0
            subdir = (attr & 2) != 0

            if file_pos != dir_pos and file_pos != parent:
                name = dir_data[pos+33:pos+33+name_len].decode('utf-8', 'ignore')

                if not subdir:
                    pat = re_name.match(name)
                    if pat:
                        name = pat.group(1)

                file_path = os.path.join(path, name)
                if subdir:
                    file_list.extend(read_dir(f, file_path, file_pos, file_len, dir_pos))
                else:
                    file_list.append((file_path, file_pos, file_len))

            pos += entry_size
        else:
            pos = (pos + 2047) & ~2047

    return file_list

def read_file_table(f):
    file_table = read_sector_form1(f, 24, 16)
    index = 0
    file_count = 0
    dir_count = 0
    dir_index = 0
    movies = False
    file_list = []

    while True:
        start_sector = struct.unpack_from("<I", file_table, index * 7)[0] & 0xFFFFFF
        if start_sector == 0xFFFFFF:
            break

        file_size = struct.unpack_from("<i", file_table, index * 7 + 3)[0]
        if file_size < 0:
            file_count = 0
            dir_index = dir_count
            movies = dir_count == 0
            dir_count += 1
        elif file_size > 0:
            file_path = os.path.join("dir%i" % dir_index, "file%i.bin" % file_count)
            file_list.append((file_path, start_sector, file_size, movies))
            file_count += 1

        index += 1
    return file_list

def main(*argv):
    for arg in argv:
        with open(arg, "rb") as f:
            # ディスクの識別
            volume_descriptor = read_sector_form1(f, 16, 1)
            system_identifier, volume_identifier = struct.unpack_from("<32s32s", volume_descriptor, 8)
            system_identifier = system_identifier.strip().decode('utf-8', 'ignore')

            if system_identifier != "PLAYSTATION":
                print(f"Not a PlayStation image: \"{system_identifier}\"")
                return

            volume_identifier = volume_identifier.strip().decode('utf-8', 'ignore')
            if volume_identifier != "XENOGEARS":
                print(f"Not a Xenogears image: \"{volume_identifier}\"")
                return

            # ファイルシステムの読み取り
            root_pos = struct.unpack_from("<I", volume_descriptor, 156 + 2)[0]
            root_len = struct.unpack_from("<I", volume_descriptor, 156 + 10)[0]
            file_list = read_dir(f, "", root_pos, root_len, root_pos)

            # ディスク 1 か 2 か判定
            disk = None
            for file in file_list:
                if file[0] == 'SLUS_006.64':
                    disk = 1
                    break
                elif file[0] == 'SLUS_006.69':
                    disk = 2
                    break

            if disk is None:
                print("Failed to find executable")
                print("Please post this to the tech-related forum on http://forums.qhimm.com/")
                return

            # CSV に LBA 情報を出力
            csv_filename = f"xenogears_iso{disk}.csv"
            with open(csv_filename, "w", newline='', encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "LBA", "File Size"])
                for name, start_sector, file_size in file_list:
                    writer.writerow([name, start_sector, file_size])
                print(f"LBA information saved to {csv_filename}")

            # 隠しファイルテーブルの取得
            hidden_files = read_file_table(f)

            # 隠しファイルの LBA 情報も CSV に保存
            hidden_csv_filename = f"xenogears_hidden_table{disk}.csv"
            with open(hidden_csv_filename, "w", newline='', encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "LBA", "File Size", "Movie Flag"])
                for name, start_sector, file_size, movie_flag in hidden_files:
                    writer.writerow([name, start_sector, file_size, movie_flag])
                print(f"Hidden file LBA information saved to {hidden_csv_filename}")

if __name__ == "__main__":
    main(*sys.argv[1:])

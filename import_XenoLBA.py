import sys
import os
import struct
import re
import csv

re_name = re.compile(r"(.*);([0-9]+)")
block_size = 2352

def read_sector_form1(f, lba, count):
    """RAWイメージのセクタ lba を count 個分読み出し、
       先頭24バイトをスキップした上でユーザーデータ(2048バイト)を連結して返す"""
    f.seek(lba * block_size)
    data = b""
    for _ in range(count):
        block = f.read(block_size)
        # モード1/フォーム1の場合、先頭24バイトはサブヘッダ等なので飛ばす
        data += block[24 : 24 + 2048]
    return data

def read_dir(f, path, dir_pos, dir_size, parent):
    dir_data = read_sector_form1(f, dir_pos, (dir_size + 2047) // 2048)
    file_list = []
    pos = 0

    while pos < len(dir_data):
        # エントリ1つの大きさ, LBA, ファイル長, 属性, ファイル名の長さ を読み込み
        (entry_size, file_pos, file_len, attr, name_len) = struct.unpack_from(
            "<BxIxxxxIxxxxxxxxxxxBxxxxxxB", dir_data, pos
        )

        if entry_size > 0:
            hidden = (attr & 1) != 0
            subdir = (attr & 2) != 0

            # 親ディレクトリや自分自身を指すエントリは無視
            if file_pos != dir_pos and file_pos != parent:
                # ファイル名部分を取得
                name = dir_data[pos + 33 : pos + 33 + name_len].decode("utf-8", "ignore")

                # ";1" などのバージョン情報を除去
                if not subdir:
                    pat = re_name.match(name)
                    if pat:
                        name = pat.group(1)

                file_path = os.path.join(path, name)
                if subdir:
                    # 再帰的にサブディレクトリを読み出し
                    file_list.extend(read_dir(f, file_path, file_pos, file_len, dir_pos))
                else:
                    file_list.append((file_path, file_pos, file_len))

            pos += entry_size
        else:
            # 0 になったら2048境界までアライメントを進める
            pos = (pos + 2047) & ~2047

    return file_list

def read_file_table(f):
    """ディスクによってはSLPS/SLUS以外に隠しファイルテーブルを持っている場合があるので、その解析"""
    file_table = read_sector_form1(f, 24, 16)  # 24LBA～のセクタを16個読み込み
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
            movies = (dir_count == 0)
            dir_count += 1
        elif file_size > 0:
            file_path = os.path.join("dir%i" % dir_index, "file%i.bin" % file_count)
            file_list.append((file_path, start_sector, file_size, movies))
            file_count += 1

        index += 1
    return file_list

def main(*argv):
    for arg in argv:
        filename = os.path.basename(arg)        # 例: "Xenogears_USA_1.bin"
        base_name = os.path.splitext(filename)[0]  # 例: "Xenogears_USA_1"

        with open(arg, "rb") as f:
            # ---------------------------------------------------------
            # ★ セクタ16(ユーザーデータ) から システムID / ボリュームID を読み取る ★
            # ---------------------------------------------------------
            volume_descriptor = read_sector_form1(f, 16, 1)  # セクタ16を1セクタ分読み込む(2048バイト)
            # volume_descriptor[ 0.. 8)  : Primary Volume Descriptor Typeなど
            # volume_descriptor[ 8..40) : system_identifier (32バイト)
            # volume_descriptor[40..72) : volume_identifier (32バイト)
            system_identifier_bytes, volume_identifier_bytes = struct.unpack_from("<32s32s", volume_descriptor, 8)

            system_identifier = system_identifier_bytes.decode("ascii", "ignore").replace('\x00', '').strip()
            volume_identifier = volume_identifier_bytes.decode("ascii", "ignore").replace('\x00', '').strip()

            # PS1ディスクかどうかの判定 (通常 "PLAYSTATION" になっているはず)
            if system_identifier != "PLAYSTATION":
                print(f'Not a PlayStation image: "{system_identifier}"')
                return

            # 北米版の場合は "XENOGEARS"、日本版の場合は "XENOGEARS" か別の文字列の可能性あり。
            # ここでは「volume_identifier に "XENOGEARS" を含む」かどうかで判定
            if "XENOGEARS" not in volume_identifier.upper():
                print(f'Not a Xenogears image: "{volume_identifier}"')
                return

            # ---------------------------------------------------------
            # ルートディレクトリを取得
            # PS1 ISO9660の PVD (sector16の user_data) のオフセット156に
            # ディレクトリレコードが格納されている(リトルエンディアン)
            # ---------------------------------------------------------
            root_pos = struct.unpack_from("<I", volume_descriptor, 156 + 2)[0]
            root_len = struct.unpack_from("<I", volume_descriptor, 156 + 10)[0]

            # ディレクトリ情報の読み出し
            file_list = read_dir(f, "", root_pos, root_len, root_pos)

            # ---------------------------------------------------------
            # ディスク 1 か 2 か判定 (日本版 & 北米版)
            # 北米版: SLUS_006.64 (Disc1), SLUS_006.69 (Disc2)
            # 日本版: SLPS_011.60 (Disc1), SLPS_011.61 (Disc2)
            # ---------------------------------------------------------
            disk = None
            for (fp, start_sector, size) in file_list:
                lower_fp = fp.upper()
                if lower_fp in ["SLUS_006.64", "SLPS_011.60"]:
                    disk = 1
                    break
                elif lower_fp in ["SLUS_006.69", "SLPS_011.61"]:
                    disk = 2
                    break

            if disk is None:
                print("Failed to find executable (SLUS_006.64/69 or SLPS_011.60/61)")
                print("Please post this to the tech-related forum on http://forums.qhimm.com/")
                return

            # ---------------------------------------------------------
            # CSV に LBA 情報を出力
            # ---------------------------------------------------------
            csv_filename = f"{base_name}_{disk}.csv"
            with open(csv_filename, "w", newline='', encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "LBA", "File Size"])
                for name, start_sector, file_size in file_list:
                    writer.writerow([name, start_sector, file_size])
                print(f"LBA information saved to {csv_filename}")

            # 隠しファイルテーブルを取得
            hidden_files = read_file_table(f)

            # 隠しファイルの LBA 情報も CSV に保存
            hidden_csv_filename = f"{base_name}_hidden_{disk}.csv"
            with open(hidden_csv_filename, "w", newline='', encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "LBA", "File Size", "Movie Flag"])
                for name, start_sector, file_size, movie_flag in hidden_files:
                    writer.writerow([name, start_sector, file_size, movie_flag])
                print(f"Hidden file LBA information saved to {hidden_csv_filename}")

if __name__ == "__main__":
    main(*sys.argv[1:])

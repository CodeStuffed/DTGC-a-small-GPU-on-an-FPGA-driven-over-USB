"""Usage: python -m unittest sw.tests.test_games"""
import math
import types
import unittest

from sw.dtgc import api, app, games
from sw.dtgc import protocol as p
from sw.dtgc.api import Canvas, Mesh, rgb
from sw.dtgc.client import Dtgc
from sw.dtgc.emulator import Device, LocalTransport


def open_gpu():
    device = Device()
    return Dtgc(LocalTransport(device)), device


def picture(device):
    return bytes(device.buffers[device.front])


def _next_cell_to_exit(start):
    """Breadth-first search over the map. Returns the first cell on a shortest way from start to the exit."""
    came_from, todo = {start: None}, [start]
    for cell in todo:
        x, y = cell
        if games.MAZE_MAP[y][x] == "X":
            while came_from[cell] not in (None, start):
                cell = came_from[cell]
            return cell
        for near in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if near not in came_from and games.Maze._cell(near[0] + 0.5, near[1] + 0.5) != "#":
                came_from[near] = cell
                todo.append(near)
    raise AssertionError("no way out")


def _keys_towards_exit(game):
    target_x, target_y = _next_cell_to_exit((int(game.x), int(game.y)))
    wanted = math.atan2(target_y + 0.5 - game.y, target_x + 0.5 - game.x)
    turn = (wanted - game.angle + math.pi) % (2 * math.pi) - math.pi
    if abs(turn) > game.TURN:
        return {"right"} if turn > 0 else {"left"}
    return {"up"}


class Api(unittest.TestCase):
    def setUp(self):
        self.gpu, self.device = open_gpu()
        self.canvas = Canvas(self.gpu)

    def shown(self):
        self.canvas.show()
        self.canvas.finish()
        return picture(self.device)

    def test_rgb_packs_the_top_bits(self):
        self.assertEqual(rgb(255, 255, 255), 0xFF)
        self.assertEqual(rgb(255, 0, 0), 0xE0)
        self.assertEqual(rgb(0, 255, 0), 0x1C)
        self.assertEqual(rgb(0, 0, 255), 0x03)

    def test_rect_off_the_left_and_top_is_cut(self):
        self.canvas.clear(0)
        self.canvas.rect(-5, -5, 10, 10, 9)
        frame = self.shown()
        self.assertEqual(frame[4 * p.WIDTH + 4], 9)
        self.assertEqual(frame[5 * p.WIDTH + 4], 0)
        self.assertEqual(frame[4 * p.WIDTH + 5], 0)

    def test_rect_fully_off_does_nothing(self):
        self.canvas.clear(0)
        for box in ((-20, 5, 10, 10), (5, -20, 10, 10), (340, 5, 10, 10), (5, 340, 10, 10)):
            self.canvas.rect(*box, 9)
        self.assertEqual(self.shown().count(9), 0)

    def test_text_draws_the_font(self):
        self.canvas.clear(0)
        width = self.canvas.text(0, 0, "1", 7, size=1)
        self.assertEqual(width, 3)
        frame = self.shown()
        rows = [frame[y * p.WIDTH:y * p.WIDTH + 3] for y in range(5)]
        self.assertEqual(rows, [b"\0\7\0", b"\7\7\0", b"\0\7\0", b"\0\7\0", b"\7\7\7"])

    def test_every_font_character_has_five_rows_of_three_bits(self):
        for character, rows in api._FONT.items():
            self.assertEqual(len(rows), 5, character)
            self.assertTrue(all(0 <= row < 8 for row in rows), character)

    def test_cube_draws_only_faces_towards_the_viewer(self):
        self.canvas.clear(0)
        self.canvas.clear_depth()
        self.canvas.draw_mesh(Mesh.cube(), angle_x=0.4, angle_y=0.6, distance=4)
        self.assertLessEqual(self.canvas.triangles_sent, 6)  # at most 3 faces of a cube can be seen
        self.assertGreater(self.canvas.triangles_sent, 0)
        frame = self.shown()
        self.assertGreater(len(frame) - frame.count(0), 1000)

    def test_near_faces_hide_far_ones(self):
        near = Mesh.cube(1.0, [(0, 255, 0)] * 6)
        far = Mesh.cube(1.0, [(255, 0, 0)] * 6)
        self.canvas.clear(0)
        self.canvas.clear_depth()
        self.canvas.draw_mesh(near, distance=4)
        self.canvas.draw_mesh(far, distance=8)   # drawn second, must still be behind
        frame = self.shown()
        middle = frame[170 * p.WIDTH + 170]
        self.assertEqual(middle & 0xE0, 0)
        self.assertNotEqual(middle & 0x1C, 0)

    def test_clear_scene_gives_the_same_pictures_as_clearing_everything(self):
        """Moving shapes, a frame with nothing, and a change of background."""
        full_device = Device()
        full = Canvas(Dtgc(LocalTransport(full_device)))
        fast_device = Device()
        fast = Canvas(Dtgc(LocalTransport(fast_device)))
        mesh = Mesh.cube()
        for frame in range(14):
            background = 3 if frame < 9 else 200
            full.clear(background)
            full.clear_depth()
            fast.clear_scene(background)
            for canvas in (full, fast):
                if frame != 5:
                    canvas.draw_mesh(mesh, (frame * 0.2 - 1, 0, 0), frame * 0.3, frame * 0.2, 4)
                    canvas.rect(frame * 7, 300, 11, 9, 77)
                    canvas.text(250, frame * 3, "HI", 15)
                canvas.show()
                canvas.finish()
            self.assertEqual(bytes(full_device.buffers[full_device.front]), bytes(fast_device.buffers[fast_device.front]), frame)
            self.assertEqual(full_device.depth, fast_device.depth, frame)

    def test_clear_scene_uses_the_fast_depth_clear_every_frame(self):
        sizes = []
        for frame in range(4):
            sent = []
            gpu = types.SimpleNamespace(clear=lambda c: sent.append("clear"), clear_depth=lambda: sent.append("clear_depth"),
                                        rect=lambda *a: sent.append("rect"), depth_rect=lambda *a: sent.append("depth_rect"),
                                        triangle=lambda t: None, swap=lambda: None)
            if frame == 0:
                canvas = Canvas(gpu)
            canvas.gpu = gpu
            canvas.clear_scene(1)
            canvas.draw_mesh(Mesh.cube())
            canvas.show()
            sizes.append(sent)
        self.assertEqual(sizes[0], ["clear", "clear_depth"])
        self.assertEqual(sizes[1], ["clear", "clear_depth"])
        self.assertEqual(sizes[2], ["rect", "clear_depth"])
        self.assertEqual(sizes[3], ["rect", "clear_depth"])

    def test_mesh_behind_the_viewer_is_skipped(self):
        self.canvas.draw_mesh(Mesh.cube(), distance=-5)
        self.assertEqual(self.canvas.triangles_sent, 0)


class PongRules(unittest.TestCase):
    def test_same_keys_same_game(self):
        a, b = games.Pong(), games.Pong()
        for frame in range(500):
            keys = {"up"} if frame % 40 < 20 else {"down"}
            a.step(keys)
            b.step(keys)
        self.assertEqual((a.ball_x, a.ball_y, a.player_score, a.cpu_score), (b.ball_x, b.ball_y, b.player_score, b.cpu_score))

    def test_paddle_stops_at_the_walls(self):
        game = games.Pong()
        for _ in range(200):
            game.step({"up"})
        self.assertEqual(game.player_y, game.TOP)
        for _ in range(200):
            game.step({"down"})
        self.assertEqual(game.player_y, p.HEIGHT - game.PADDLE_H)

    def test_ball_stays_on_the_picture_vertically(self):
        game = games.Pong()
        for _ in range(3000):
            game.step(set())
            self.assertGreaterEqual(game.ball_y, game.TOP)
            self.assertLessEqual(game.ball_y, p.HEIGHT - game.BALL)

    def test_idle_player_loses_to_the_cpu(self):
        game = games.Pong()
        for _ in range(20000):
            game.step(set())
        self.assertTrue(game.over)
        self.assertEqual(game.cpu_score, game.WIN_SCORE)

    def test_a_bot_using_the_keys_can_beat_the_cpu(self):
        wins = 0
        for seed in range(10):
            game = games.Pong(seed)
            for _ in range(18000):  # ten minutes at 30 frames per second: a game must not drag on longer
                if game.over:
                    break
                gap = game.ball_y + game.BALL // 2 - (game.player_y + game.PADDLE_H // 2)
                game.step({"down"} if gap > 3 else {"up"} if gap < -3 else set())
            self.assertTrue(game.over, seed)
            wins += game.player_score > game.cpu_score
        self.assertGreater(wins, 0)

    def test_paddle_returns_the_ball(self):
        game = games.Pong()
        game.ball_x, game.ball_y, game.speed_x, game.speed_y = 26, game.player_y + 10, -4, 0
        game.step(set())
        self.assertGreater(game.speed_x, 0)


class MazeRules(unittest.TestCase):
    def test_walls_stop_the_player(self):
        game = games.Maze()
        for _ in range(500):
            game.step({"up"})
            self.assertNotEqual(game._cell(game.x, game.y), "#")

    def test_map_rows_are_equal_and_have_one_exit(self):
        self.assertEqual(len({len(row) for row in games.MAZE_MAP}), 1)
        self.assertEqual(sum(row.count("X") for row in games.MAZE_MAP), 1)

    def test_exit_can_be_reached(self):
        # A flood fill, because a maze with no way out would be a poor joke.
        seen, todo = set(), [(1, 1)]
        while todo:
            x, y = todo.pop()
            if (x, y) in seen or games.Maze._cell(x + 0.5, y + 0.5) == "#":  # off the map counts as wall
                continue
            seen.add((x, y))
            todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        self.assertTrue(any(games.MAZE_MAP[y][x] == "X" for x, y in seen))

    def test_a_wall_straight_ahead_is_at_the_right_distance(self):
        game = games.Maze()
        game.x, game.y, game.angle = 1.5, 1.5, 3.14159265
        distance, _, kind, _ = game._cast(game.angle)
        self.assertAlmostEqual(distance, 0.5, places=3)
        self.assertEqual(kind, "#")

    def test_player_cannot_press_into_a_wall(self):
        # Walking and turning at once used to end with the view inside the wall: one flat colour.
        game = games.Maze()
        for frame in range(3000):
            game.step({"up", "left"} if frame % 300 < 150 else {"up", "right"})
            for angle in range(0, 628, 20):
                self.assertGreater(game._cast(angle / 100)[0], game.BODY * 0.99)

    def test_wall_right_in_front_still_shows_detail(self):
        gpu, device = open_gpu()
        game, canvas = games.Maze(), Canvas(gpu)
        game.angle = 3.14159265
        for _ in range(30):
            game.step({"up"})
        game.draw(canvas)
        canvas.show()
        canvas.finish()
        self.assertGreater(len(set(picture(device))), 1)

    def test_a_bot_can_walk_out_using_only_the_keys(self):
        game = games.Maze()
        for _ in range(20000):
            if game.won:
                break
            game.step(_keys_towards_exit(game))
        self.assertTrue(game.won)

    def test_standing_on_the_exit_wins(self):
        game = games.Maze()
        game.x, game.y, game.angle = 14.5, 11.5, 0.0
        for _ in range(20):
            game.step({"up"})
        self.assertTrue(game.won)


class DodgeRules(unittest.TestCase):
    def test_score_goes_up_as_rocks_pass(self):
        game = games.Dodge()
        for rock in game.rocks:
            rock[0] = 3.0  # out of the way
        for _ in range(200):
            game.x = -3.0
            game.step(set())
        self.assertGreater(game.score, 0)

    def test_hit_ends_the_game(self):
        game = games.Dodge()
        game.rocks[0][:] = [0.0, 0.0, 1.9]
        game.step(set())
        self.assertTrue(game.over)

    def test_player_stays_in_the_lane(self):
        game = games.Dodge()
        for _ in range(100):
            game.step({"left", "up"})
        self.assertEqual((game.x, game.y), (-game.LANE, -game.LANE))


class EveryGameDraws(unittest.TestCase):
    def test_no_command_is_refused_and_the_picture_changes(self):
        for name, game_class in games.GAMES.items():
            gpu, device = open_gpu()
            game, canvas = game_class(), Canvas(gpu)
            for _ in range(getattr(game, "INTRO_FRAMES", 0)):   # the kart countdown holds still for 3 s
                game.step(set())
            frames = []
            for frame in range(40):
                game.step({"up"} if frame % 2 else {"left"})
                game.draw(canvas)
                canvas.show()
                canvas.finish()
                frames.append(picture(device))
            self.assertGreater(len(set(frames)), 5, name)
            self.assertGreater(len(set(frames[-1])), 1, name)

    def test_backgrounds_are_not_rounded_away_to_black(self):
        # Blue has 2 bits, so a dark blue under 64 silently became black. Only a picture showed it.
        for name, game_class in games.GAMES.items():
            gpu, device = open_gpu()
            canvas = Canvas(gpu)
            game_class().draw(canvas)
            canvas.show()
            canvas.finish()
            self.assertNotEqual(picture(device)[p.WIDTH * 40 + p.WIDTH // 2], 0, name)

    def test_finished_screens_draw_too(self):
        for game in (games.Pong(), games.Maze(), games.Dodge()):
            gpu, _ = open_gpu()
            game.over = game.won = True
            game.draw(Canvas(gpu))
            gpu.flush()


class Windows(unittest.TestCase):
    """Opens real windows for a moment. Skipped on a machine with no screen, such as a build server."""

    def setUp(self):
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception as error:
            self.skipTest(f"no screen: {error}")

    def test_each_game_plays_a_few_frames_in_its_window(self):
        for name in games.GAMES:
            gpu, device = open_gpu()
            games.play(name, gpu, device, fps=200, frames=3)
            self.assertGreaterEqual(device.expected, 3, name)

    def test_app_window_opens_and_closes(self):
        app.main(close_after_ms=50)


class AppButtons(unittest.TestCase):
    def test_every_button_is_a_command_that_exists(self):
        every = [app.arguments_for(version, action) for version, _ in app.VERSIONS for _, action in app.ACTIONS]
        for arguments in filter(None, every):
            lines = []
            self.assertEqual(app.run_command([*arguments, "--help"], lines.append), 0, arguments)
            self.assertTrue(lines)

    def test_a_failing_command_reports_its_exit_code(self):
        self.assertNotEqual(app.run_command(["no-such-command"], lambda _: None), 0)


if __name__ == "__main__":
    unittest.main()

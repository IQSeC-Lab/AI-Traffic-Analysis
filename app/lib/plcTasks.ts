/**
 * Agent to PLC's 18 tasks as the Information page explains them. The requests are the agents'
 * own words from api/experiments/plc_plant.py (TASKS); change both together.
 */

export type TaskInfo = {
  request: string;
  /** The state of the brewery the PLC starts in: Normal, Fault or Changeover. */
  state: string;
  tools: string;
  explanation: string;
};

export type TaskGroup = { category: string; about: string; tasks: TaskInfo[] };

export const PLC_TASKS: TaskGroup[] = [
  {
    category: "Monitor",
    about: "Read a few values and report them",
    tasks: [
      {
        request: "Report Boiler #2's current temperature, its target temperature and whether its heater is on.",
        state: "Normal",
        tools: "read",
        explanation:
          "Three reads of the simulator's own boiler, the smallest task of the set. The boiler heats to 80 °C, switches its heater off, cools to 10 °C and switches it on again, so the answer depends on when the agents read.",
      },
      {
        request: "Report each fermenter's temperature and target temperature, and name any fermenter more than 1 °C off its target.",
        state: "Normal",
        tools: "read",
        explanation:
          "Six reads, two per fermenter. Fermenter C starts 1.4 °C above its target and A and B within 0.4 °C. With their cooling off all three warm 0.02 °C a second, so a slow run can find A or B past 1 °C too.",
      },
    ],
  },
  {
    category: "Compare",
    about: "Read the same values of several devices and pick one",
    tasks: [
      {
        request: "Which fermenter is furthest from its target temperature, and by how many degrees?",
        state: "Normal",
        tools: "read",
        explanation:
          "The same six reads as Monitor's second task, but the agents must weigh them and give one answer: fermenter C, about 1.4 °C at the start.",
      },
      {
        request: "Which fermenter holds the most beer, and which batch is in it?",
        state: "Normal",
        tools: "read",
        explanation:
          "Three level reads and one batch read. Fermenter C is the fullest at 88 %, with batch STOUT-0415. Levels only move while an outlet valve is open, so the answer holds for the whole task.",
      },
    ],
  },
  {
    category: "Explore",
    about: "Browse the PLC to find what it holds",
    tasks: [
      {
        request: "Browse the brewery on the PLC and list every device in it with the values each one has.",
        state: "Normal",
        tools: "browse, read",
        explanation:
          "Explore tasks are not given the node list, only the brewery's folder, so the agents have to browse it and then each of its six devices. A browse answer carries every value of a device with its description, which makes these the largest responses of the set.",
      },
      {
        request: "Find out which values of the bottling line an operator can change and which are sensor readings, and report both lists.",
        state: "Normal",
        tools: "browse",
        explanation:
          "One browse of the bottling line marks each value as can be changed or read only: Running, Speed and Mode can be changed, BottlesFilled, RejectCount and HourlyOutput are sensors.",
      },
    ],
  },
  {
    category: "Control",
    about: "Change settings or call a method",
    tasks: [
      {
        request: "Switch Boiler #2's heater off with its Switch method, then set the stacklight to red.",
        state: "Normal",
        tools: "call, write",
        explanation:
          "The one task built around a method call. The call tool first looks up the method's object and the type of its argument, then calls Switch with false, all on one connection. Then one write. The boiler cools from then on.",
      },
      {
        request: "Stop the bottling line and switch it to Manual mode.",
        state: "Normal",
        tools: "write",
        explanation:
          "Two writes. A write first reads the node's type and then writes, two requests on one connection. The bottle counter stops once Running is false.",
      },
    ],
  },
  {
    category: "Closed loop",
    about: "Change a setting, watch the plant respond, change it back",
    tasks: [
      {
        request: "Fermenter B is too warm. Turn its cooling on, keep checking its temperature, and turn the cooling off once it is at its target.",
        state: "Fault",
        tools: "write, read",
        explanation:
          "Fermenter B starts at 18.5 °C against a 12 °C target and keeps warming until its cooling is on. Then it cools 0.2 °C a second, about 33 seconds to the target. The agents have to keep reading, and the gaps between their reads are the model's thinking time, so a slow model overshoots.",
      },
      {
        request: "Start the bottling line at 120 bottles a minute, keep checking how many bottles are filled, and stop it once 100 bottles are filled.",
        state: "Changeover",
        tools: "write, read",
        explanation:
          "The line starts stopped with its counter at 0. At 120 a minute it fills 2 bottles a second, so the agents read the counter for about 50 seconds before they stop it.",
      },
    ],
  },
  {
    category: "Incident",
    about: "Respond to a fault: act on it and raise the stacklight",
    tasks: [
      {
        request: "The bottling line is rejecting too many bottles. Stop it, set the stacklight to yellow, and report how many bottles were rejected.",
        state: "Fault",
        tools: "write, read",
        explanation:
          "In the fault state the line rejects every 5th bottle (every 50th otherwise), so its reject count climbs from 412 until the line stops. Writes first, then a read of the final count.",
      },
      {
        request: "Fermenter C's level is dropping although its outlet valve is closed. Measure how fast it drops, set the stacklight to red, and report when the fermenter will be empty.",
        state: "Fault",
        tools: "read, write",
        explanation:
          "A leak drains fermenter C 0.5 % a second whatever its valve says. Two level reads some seconds apart give the rate; from 88 % it is empty in about three minutes. Nothing the agents can write stops the leak.",
      },
    ],
  },
  {
    category: "History",
    about: "Read a 24 or 48-hour log and summarize it",
    tasks: [
      {
        request: "Read fermenter A's temperature log and report at which hour it was warmest, and how warm.",
        state: "Normal",
        tools: "read",
        explanation:
          "One read returns 48 hourly values, oldest first: one large response instead of many small ones. A warm spell peaks at hour 31 (counting from 0), 19.56 °C.",
      },
      {
        request: "Read the bottling line's hourly output and report the busiest and the slowest hour.",
        state: "Normal",
        tools: "read",
        explanation:
          "One read of 24 hourly bottle counts, busy by day and slow at night. The busiest is hour 13 with 5,380 bottles, the slowest hour 1 with 511.",
      },
    ],
  },
  {
    category: "Anomaly",
    about: "Find something unusual, live or in a log",
    tasks: [
      {
        request: "Check every fermenter's temperature and level twice, a little apart, and report anything that is not as it should be.",
        state: "Fault",
        tools: "read",
        explanation:
          "Twelve reads in two passes, live data. Comparing the passes shows what the fault state hides: fermenter B far above its target with its cooling off, and fermenter C losing level with its valve closed.",
      },
      {
        request: "Fermenter C's level log has one sudden drop. Find at which hour it happened and how large it was.",
        state: "Normal",
        tools: "read",
        explanation:
          "The same kind of question asked of stored data: one read of 48 values. The level falls 27.1 points, from 91.3 % to 64.2 %, between hours 19 and 20.",
      },
    ],
  },
  {
    category: "Setpoints",
    about: "Write several settings at once",
    tasks: [
      {
        request: "Load the Stout recipe: set the active recipe to Stout, the mash temperature to 67 °C and the boil time to 75 minutes.",
        state: "Changeover",
        tools: "write, read",
        explanation:
          "Three writes of three types (text, a decimal and a whole number), then reads to check them. The recipe starts as IPA, 65 °C and 60 minutes.",
      },
      {
        request: "Fermenter C is empty and clean. Set its target temperature to 19 °C, close its outlet valve and switch its cooling off.",
        state: "Changeover",
        tools: "write, read",
        explanation:
          "Three writes. Fermenter C starts empty at 6 °C with its cooling on and its valve open; once the cooling is off it warms 0.02 °C a second.",
      },
    ],
  },
];

import WelcomePage from "../components/WelcomePage";

export default function SearchPage() {
  return (
    <WelcomePage
      title="智能论文检索"
      placeholder={"描述你的研究方向或关键词...\n例如：最近两年关于 Vision Transformer 在医学影像分割的 SOTA 方法"}
      suggestions={[
        "Transformer 在 NLP 的最新进展",
        "强化学习 + 机器人控制",
        "图神经网络 药物发现",
      ]}
      requireGithubUrl={false}
    />
  );
}

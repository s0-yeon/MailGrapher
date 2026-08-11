export default function Footer({ brand = 'MailGrapher' }) {
  return (
    <footer id="app-footer">
      <div className="float-end">{brand}</div>
      <div className="clearfix"></div>
    </footer>
  );
}
